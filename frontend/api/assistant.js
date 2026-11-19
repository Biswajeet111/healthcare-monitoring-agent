/**
 * HealthGuard AI — Vercel Serverless Educational AI Assistant Endpoint
 * Route: /api/assistant
 *
 * Uses Groq cloud inference via server-side environment variables ONLY.
 * GROQ_API_KEY is never exposed to the browser or Vite frontend bundle.
 *
 * IMPORTANT: Responses from this lightweight Vercel demo endpoint use general
 * LLM knowledge and are NOT RAG-grounded against ChromaDB or uploaded PDFs.
 */

const DEFAULT_GROQ_MODEL = 'qwen/qwen3.8-27b';
const DEFAULT_GROQ_BASE_URL = 'https://api.groq.com/openai/v1';
const MAX_QUESTION_LEN = 600;
const MIN_QUESTION_LEN = 3;
const REQUEST_TIMEOUT_MS = 20_000;

// Per-instance sliding-window rate limiter (basic public demo abuse protection)
const MINUTE_WINDOW_MS = 60_000;
const HOUR_WINDOW_MS = 3_600_000;
const MAX_REQUESTS_PER_MINUTE = 10;
const MAX_REQUESTS_PER_HOUR = 40;
const ipBuckets = new Map();

const DISCLAIMER =
  'This is educational information only and does not replace professional medical advice.';

const NON_RAG_LIMITATION =
  'This Vercel educational demo uses general Groq LLM inference and is not RAG-grounded in the local clinical document index or uploaded PDF reports.';

const EMERGENCY_PATTERN =
  /\b(chest pain|crushing chest|heart attack|difficulty breathing|can'?t breathe|shortness of breath|stroke|slurred speech|face drooping|suicid(?:e|al)|kill myself|overdose|severe bleeding|unconscious|seizure|anaphylaxis|severe allergic reaction)\b/i;

const UNSAFE_CLINICAL_ACTION_PATTERN =
  /\b(prescribe me|write me a prescription|what dose should i take|should i stop taking|can i stop my medication|double my dose|change my dosage|diagnose me|tell me what disease i have)\b/i;

const SYSTEM_PROMPT = `You are HealthGuard AI (Educational Demo), a general health-information assistant.

STRICT MEDICAL SAFETY RULES:
- Provide clear, accessible educational health information only.
- NEVER diagnose medical conditions or interpret personal measurements as confirmed diseases.
- NEVER prescribe medications, recommend specific dosages, or advise starting, stopping, or changing prescribed treatments.
- NEVER claim that your answer was retrieved from clinical guidelines, a vector database, RAG documents, or uploaded patient lab reports.
- NEVER invent numbered citations like [1], [2], document titles, or study references.
- For potential emergencies (chest pain, breathing difficulty, stroke signs, suicidal thoughts, severe bleeding, overdose), advise contacting local emergency services immediately.
- Keep answers concise, well-structured, and practical (under 220 words).
- End every answer with: "${DISCLAIMER}"`;

function getClientIp(req) {
  const fwd = req.headers?.['x-forwarded-for'];
  if (typeof fwd === 'string' && fwd.trim()) {
    return fwd.split(',')[0].trim();
  }
  const realIp = req.headers?.['x-real-ip'];
  if (typeof realIp === 'string' && realIp.trim()) {
    return realIp.trim();
  }
  return req.socket?.remoteAddress || 'unknown';
}

function checkRateLimit(ip) {
  const now = Date.now();
  const timestamps = (ipBuckets.get(ip) || []).filter((ts) => now - ts < HOUR_WINDOW_MS);

  const lastMinuteCount = timestamps.filter((ts) => now - ts < MINUTE_WINDOW_MS).length;
  if (lastMinuteCount >= MAX_REQUESTS_PER_MINUTE) {
    const oldestInMinute = timestamps.find((ts) => now - ts < MINUTE_WINDOW_MS) || now;
    const retryAfterSec = Math.max(1, Math.ceil((MINUTE_WINDOW_MS - (now - oldestInMinute)) / 1000));
    ipBuckets.set(ip, timestamps);
    return { allowed: false, retryAfterSec, reason: 'Too many requests. Please wait a moment before asking another question.' };
  }

  if (timestamps.length >= MAX_REQUESTS_PER_HOUR) {
    const retryAfterSec = Math.max(60, Math.ceil((HOUR_WINDOW_MS - (now - timestamps[0])) / 1000));
    ipBuckets.set(ip, timestamps);
    return { allowed: false, retryAfterSec, reason: 'Hourly demo request limit reached. Please try again later.' };
  }

  timestamps.push(now);
  ipBuckets.set(ip, timestamps);

  // Bound in-memory map size on long-lived serverless instances
  if (ipBuckets.size > 500) {
    const firstKey = ipBuckets.keys().next().value;
    if (firstKey) ipBuckets.delete(firstKey);
  }
  return { allowed: true, retryAfterSec: 0 };
}

function stripThinkTags(text) {
  if (!text) return '';
  return String(text).replace(/<think>[\s\S]*?<\/think>\s*/gi, '').trim();
}

function parseBody(req) {
  if (req.body && typeof req.body === 'object') {
    return req.body;
  }
  if (typeof req.body === 'string' && req.body.trim()) {
    if (req.body.length > 4096) {
      return { __tooLarge: true };
    }
    try {
      return JSON.parse(req.body);
    } catch {
      return null;
    }
  }
  return null;
}

export default async function handler(req, res) {
  res.setHeader('Cache-Control', 'no-store');
  res.setHeader('X-Content-Type-Options', 'nosniff');

  const apiKey = (process.env.GROQ_API_KEY || '').trim();
  const model = (process.env.GROQ_MODEL || DEFAULT_GROQ_MODEL).trim();
  const baseUrl = (process.env.GROQ_BASE_URL || DEFAULT_GROQ_BASE_URL).replace(/\/$/, '');

  if (req.method === 'GET') {
    return res.status(200).json({
      available: Boolean(apiKey),
      llm_provider: 'groq',
      llm_available: Boolean(apiKey),
      active_model: model,
      rag_grounded: false,
      mode: 'vercel_educational_demo',
      limitation: NON_RAG_LIMITATION,
    });
  }

  if (req.method !== 'POST') {
    res.setHeader('Allow', 'GET, POST');
    return res.status(405).json({ detail: 'Method not allowed.' });
  }

  // Basic per-IP rate limiting
  const clientIp = getClientIp(req);
  const limit = checkRateLimit(clientIp);
  if (!limit.allowed) {
    res.setHeader('Retry-After', String(limit.retryAfterSec));
    return res.status(429).json({
      answer: null,
      error: limit.reason,
      sources: [],
      rag_grounded: false,
      limitations: [NON_RAG_LIMITATION, 'Demo rate limit exceeded.'],
      disclaimer: DISCLAIMER,
    });
  }

  const body = parseBody(req);
  if (!body) {
    return res.status(400).json({ detail: 'Invalid JSON request body.' });
  }
  if (body.__tooLarge) {
    return res.status(413).json({ detail: 'Request payload is too large.' });
  }

  const rawQuestion = typeof body.question === 'string' ? body.question.trim() : '';
  if (rawQuestion.length < MIN_QUESTION_LEN) {
    return res.status(400).json({
      detail: `Question must be at least ${MIN_QUESTION_LEN} characters long.`,
    });
  }
  if (rawQuestion.length > MAX_QUESTION_LEN) {
    return res.status(400).json({
      detail: `Question must be at most ${MAX_QUESTION_LEN} characters in this public demo.`,
    });
  }

  // Deterministic medical safety screening before calling LLM
  if (EMERGENCY_PATTERN.test(rawQuestion)) {
    return res.status(200).json({
      answer:
        'If you or someone nearby may be experiencing a medical emergency (such as chest pain, trouble breathing, stroke symptoms, severe bleeding, overdose, or thoughts of self-harm), contact your local emergency services or go to the nearest emergency department immediately. Do not wait for an AI response.\n\n' +
        DISCLAIMER,
      sources: [],
      rag_grounded: false,
      limitations: ['Emergency safety guidance triggered before LLM generation.', NON_RAG_LIMITATION],
      disclaimer: DISCLAIMER,
      model_used: 'safety-gate',
      provider_used: 'deterministic',
    });
  }

  if (UNSAFE_CLINICAL_ACTION_PATTERN.test(rawQuestion)) {
    return res.status(200).json({
      answer:
        'HealthGuard AI cannot diagnose medical conditions, prescribe medications, determine personal dosages, or advise stopping or changing prescribed treatments. Please consult a licensed physician or pharmacist regarding diagnosis or medication decisions.\n\n' +
        DISCLAIMER,
      sources: [],
      rag_grounded: false,
      limitations: ['Non-diagnostic safety boundary enforced.', NON_RAG_LIMITATION],
      disclaimer: DISCLAIMER,
      model_used: 'safety-gate',
      provider_used: 'deterministic',
    });
  }

  if (!apiKey) {
    return res.status(503).json({
      answer: null,
      error: 'The Groq AI service is not configured on this Vercel deployment (missing GROQ_API_KEY).',
      sources: [],
      rag_grounded: false,
      limitations: ['Server-side GROQ_API_KEY is not configured.', NON_RAG_LIMITATION],
      disclaimer: DISCLAIMER,
    });
  }

  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS);

  try {
    const groqRes = await fetch(`${baseUrl}/chat/completions`, {
      method: 'POST',
      headers: {
        Authorization: `Bearer ${apiKey}`,
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({
        model,
        messages: [
          { role: 'system', content: SYSTEM_PROMPT },
          {
            role: 'user',
            content:
              `Educational health question (general knowledge only; no clinical RAG documents or personal medical records are attached):\n${rawQuestion}`,
          },
        ],
        temperature: 0.2,
        max_tokens: 450,
      }),
      signal: controller.signal,
    });

    if (groqRes.status === 429) {
      const retryAfter = groqRes.headers.get('retry-after') || '15';
      res.setHeader('Retry-After', retryAfter);
      return res.status(429).json({
        answer: null,
        error: 'The Groq free-tier rate limit was temporarily reached. Please wait ~15 seconds and try again.',
        sources: [],
        rag_grounded: false,
        limitations: ['Groq API rate limit reached (HTTP 429).', NON_RAG_LIMITATION],
        disclaimer: DISCLAIMER,
      });
    }

    if (!groqRes.ok) {
      let providerMessage = `Upstream AI error (HTTP ${groqRes.status})`;
      try {
        const errJson = await groqRes.json();
        const msg = errJson?.error?.message;
        if (typeof msg === 'string' && msg.trim() && groqRes.status !== 401 && groqRes.status !== 403) {
          providerMessage = msg.trim().slice(0, 200);
        } else if (groqRes.status === 401 || groqRes.status === 403) {
          providerMessage = 'Cloud LLM authentication failed on the server.';
        }
      } catch {
        // Ignore body parse failure
      }
      return res.status(502).json({
        answer: null,
        error: providerMessage,
        sources: [],
        rag_grounded: false,
        limitations: [NON_RAG_LIMITATION],
        disclaimer: DISCLAIMER,
      });
    }

    const data = await groqRes.json();
    const rawContent = data?.choices?.[0]?.message?.content || '';
    let answerText = stripThinkTags(rawContent);

    if (!answerText) {
      return res.status(502).json({
        answer: null,
        error: 'The language model returned an empty response. Please try again.',
        sources: [],
        rag_grounded: false,
        limitations: [NON_RAG_LIMITATION],
        disclaimer: DISCLAIMER,
      });
    }

    if (!answerText.toLowerCase().includes('educational information only')) {
      answerText = `${answerText}\n\n${DISCLAIMER}`;
    }

    return res.status(200).json({
      answer: answerText,
      sources: [],
      rag_grounded: false,
      limitations: [NON_RAG_LIMITATION],
      disclaimer: DISCLAIMER,
      model_used: data?.model || model,
      provider_used: 'groq',
    });
  } catch (err) {
    const isTimeout = err && typeof err === 'object' && err.name === 'AbortError';
    return res.status(isTimeout ? 504 : 502).json({
      answer: null,
      error: isTimeout
        ? 'The AI request timed out. Please try again.'
        : 'Unable to reach the cloud AI provider right now. Please try again shortly.',
      sources: [],
      rag_grounded: false,
      limitations: [NON_RAG_LIMITATION],
      disclaimer: DISCLAIMER,
    });
  } finally {
    clearTimeout(timeoutId);
  }
}
