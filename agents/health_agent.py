import os
import joblib
import pandas as pd
from pathlib import Path

from langchain_groq import ChatGroq
from langchain_chroma import Chroma
from langchain_community.embeddings import HuggingFaceEmbeddings
from dotenv import load_dotenv

load_dotenv()

REPO_ROOT = Path(__file__).parent.parent.resolve()
MODELS_DIR = (REPO_ROOT / "models").resolve()
DATA_DIR = (REPO_ROOT / "data").resolve()

# Load model and scaler
model_path = MODELS_DIR / "health_risk_model.pkl"
scaler_path = MODELS_DIR / "scaler.pkl"

if model_path.exists() and scaler_path.exists():
    model = joblib.load(model_path)
    scaler = joblib.load(scaler_path)
else:
    model = None
    scaler = None

# Initialize Retriever
db_path = str(DATA_DIR / "vector_db")
try:
    embeddings = HuggingFaceEmbeddings(
        model_name="sentence-transformers/all-MiniLM-L6-v2"
    )
    vector_store = Chroma(
        persist_directory=db_path,
        embedding_function=embeddings,
    )
    retriever = vector_store.as_retriever(search_kwargs={"k": 3})
except Exception as e:
    retriever = None

# Initialize LLM
groq_key = os.getenv("GROQ_API_KEY")
if groq_key:
    try:
        llm = ChatGroq(
            api_key=groq_key,
            model="llama-3.1-8b-instant",
            temperature=0
        )
    except Exception:
        llm = None
else:
    llm = None

def get_medical_guidance(query):
    if not retriever:
        return "Medical knowledge base is not initialized or vector_db is missing."
    docs = retriever.invoke(query)
    context = "\n\n".join([doc.page_content for doc in docs])
    return context

def predict_diabetes(pregnancies, glucose, blood_pressure,
                     skin_thickness, insulin, bmi,
                     diabetes_pedigree, age):
    if not model or not scaler:
        return "Model not initialized. Please run health_analytics.ipynb to train the model."
        
    data = pd.DataFrame([{
        "Pregnancies": pregnancies,
        "Glucose": glucose,
        "BloodPressure": blood_pressure,
        "SkinThickness": skin_thickness,
        "Insulin": insulin,
        "BMI": bmi,
        "DiabetesPedigreeFunction": diabetes_pedigree,
        "Age": age
    }])

    data_scaled = scaler.transform(data)
    prediction = model.predict(data_scaled)[0]

    if prediction == 1:
        return "High Diabetes Risk"
    else:
        return "Low Diabetes Risk"

def healthcare_ai_agent(patient_data):
    if not llm:
        return "LLM API Key not configured. Please add GROQ_API_KEY to your .env file."
        
    risk = predict_diabetes(**patient_data)
    medical_context = get_medical_guidance("diabetes treatment and prevention")

    prompt = f"""
You are a professional healthcare AI assistant.

Rules:
1. Use ONLY the provided medical guidelines.
2. Do NOT add external medical knowledge.
3. If information is not present in the guidelines, say:
   "The available medical guidelines do not provide enough information."

Patient Health Risk Prediction:
{risk}

Using the medical guidelines below,
explain the patient's condition and suggest monitoring or prevention advice.

Medical Guidelines:
{medical_context}
"""

    try:
        response = llm.invoke(prompt)
        return response.content
    except Exception as e:
        return f"Error communicating with LLM: {str(e)}"
