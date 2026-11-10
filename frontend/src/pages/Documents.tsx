import { useCallback, useEffect, useRef, useState } from 'react';
import { CheckCircle2, Database, FileText, RefreshCw, ShieldCheck, Trash2, Upload } from 'lucide-react';
import { deleteDocument, errorMessage, fmtDateTime, indexDocument, listDocuments, uploadDocument, type MedicalDocument, type UserProfile } from '../api';
import { Alert, Badge, ConfirmButton, Empty, Spinner } from '../components/ui';

function fmtSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(2)} MB`;
}

export default function Documents({ user }: { user: UserProfile | null }) {
  const [docs, setDocs] = useState<MedicalDocument[] | null>(null);
  const [uploading, setUploading] = useState(false);
  const [indexingId, setIndexingId] = useState<number | null>(null);
  const [msg, setMsg] = useState<{ kind: 'success' | 'error' | 'warn'; text: string } | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);

  const load = useCallback(async () => {
    if (!user) return;
    try { const r = await listDocuments(); setDocs(r.documents); }
    catch (e) { setDocs([]); setMsg({ kind: 'error', text: errorMessage(e, 'Could not load documents') }); }
  }, [user]);
  useEffect(() => { void load(); }, [load]);

  async function onUpload(file: File | undefined) {
    if (!file) return;
    if (file.type && file.type !== 'application/pdf' && !file.name.toLowerCase().endsWith('.pdf')) {
      setMsg({ kind: 'error', text: 'Only PDF documents are supported.' });
      if (fileRef.current) fileRef.current.value = '';
      return;
    }
    setUploading(true); setMsg(null);
    try {
      const r = await uploadDocument(file);
      setMsg({ kind: 'success', text: `"${r.filename}" uploaded and submitted for indexing.` });
      await load();
    } catch (e) { setMsg({ kind: 'error', text: errorMessage(e, 'Document upload failed') }); }
    finally { setUploading(false); if (fileRef.current) fileRef.current.value = ''; }
  }

  async function onIndex(doc: MedicalDocument) {
    setIndexingId(doc.id); setMsg(null);
    try {
      const r = await indexDocument(doc.id);
      const status = String(r.status ?? 'indexed');
      if (status === 'failed' || status === 'error') {
        setMsg({ kind: 'error', text: String(r.message ?? `Indexing failed for "${doc.filename}".`) });
      } else if (status === 'not_applicable') {
        setMsg({ kind: 'warn', text: String(r.message ?? `"${doc.filename}" does not contain enough extractable text to index.`) });
      } else {
        setMsg({ kind: 'success', text: `"${doc.filename}" indexed (${r.chunk_count ?? 0} chunks).` });
      }
      await load();
    } catch (e) { setMsg({ kind: 'error', text: errorMessage(e, 'Indexing failed') }); }
    finally { setIndexingId(null); }
  }

  async function onDelete(doc: MedicalDocument) {
    setMsg(null);
    try {
      await deleteDocument(doc.id);
      setMsg({ kind: 'success', text: `"${doc.filename}" deleted.` });
      await load();
    } catch (e) { setMsg({ kind: 'error', text: errorMessage(e, 'Delete failed') }); }
  }

  if (!user) return <Alert kind="info">Sign in to the live backend to upload and manage medical documents.</Alert>;

  return <div className="two-cols">
    <div className="panel">
      <div className="panel-heading"><div><h3>Medical documents</h3><p>Upload PDF reports to include in private RAG searches</p></div>
        <div className="row-actions">
          <input ref={fileRef} type="file" accept="application/pdf,.pdf" hidden onChange={e => void onUpload(e.target.files?.[0])} />
          <button type="button" className="btn btn-primary" disabled={uploading} onClick={() => fileRef.current?.click()}><Upload size={15} />{uploading ? 'Uploading…' : 'Upload PDF'}</button>
          <button type="button" className="icon-btn" onClick={() => void load()} aria-label="Refresh documents"><RefreshCw size={16} /></button>
        </div>
      </div>
      {msg && <Alert kind={msg.kind} onClose={() => setMsg(null)}>{msg.text}</Alert>}
      {docs === null ? <Spinner /> : docs.length === 0 ? <Empty>No documents uploaded yet. Upload a PDF lab report or clinical summary above.</Empty> : <div className="list">
        {docs.map(d => <div className="list-row doc-row" key={d.id}>
          <span className="feature-icon blue"><FileText size={18} /></span>
          <div>
            <b>{d.filename}</b>
            <small>{fmtSize(d.file_size)} · Uploaded {fmtDateTime(d.uploaded_at)}{d.chunk_count != null ? ` · ${d.chunk_count} chunks` : ''}{!d.has_extracted_text ? ' · No extractable text' : ''}</small>
          </div>
          <Badge value={d.index_status} />
          <div className="row-actions">
            {d.has_extracted_text && <button type="button" className="btn btn-ghost small" disabled={indexingId === d.id} onClick={() => void onIndex(d)}><Database size={13} />{indexingId === d.id ? 'Indexing…' : d.index_status === 'indexed' ? 'Re-index' : 'Index'}</button>}
            <ConfirmButton className="btn btn-danger small" label={<><Trash2 size={13} /> Delete</>} confirmLabel="Confirm delete" onConfirm={() => onDelete(d)} />
          </div>
        </div>)}
      </div>}
    </div>
    <div className="panel info-panel">
      <ShieldCheck size={28} />
      <h3>Document privacy & indexing</h3>
      <p>Uploaded PDFs are stored locally on the server, verified with SHA-256 hashing, and embedded into your isolated user collection in ChromaDB.</p>
      <div className="info-line"><CheckCircle2 size={17} /> User-scoped retrieval isolation</div>
      <div className="info-line"><CheckCircle2 size={17} /> Automatic text extraction on upload</div>
      <div className="info-line"><CheckCircle2 size={17} /> Clean vector removal on delete</div>
      <p className="fineprint">Scanned image-only PDFs without embedded text cannot be indexed unless converted to searchable text first.</p>
    </div>
  </div>;
}

