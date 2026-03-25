import streamlit as st
import os

from dotenv import load_dotenv
load_dotenv()

st.set_page_config(page_title="AI Health Intelligence", layout="centered")

st.title("AI-Powered Health Intelligence System 🏥")
st.write("Welcome! This app provides health tracking and personalized AI insights based on clinical guidelines.")

if not os.getenv("GROQ_API_KEY"):
    st.warning("⚠️ GROQ_API_KEY is missing in your environment. AI features will not work.")

# Sidebar for patient data
st.sidebar.header("Patient Data")
st.sidebar.write("Enter vitals to assess diabetes risk and get AI guidance.")

pregnancies = st.sidebar.number_input("Pregnancies", min_value=0, max_value=20, value=2)
glucose = st.sidebar.number_input("Glucose", min_value=0, max_value=300, value=140)
blood_pressure = st.sidebar.number_input("Blood Pressure", min_value=0, max_value=200, value=85)
skin_thickness = st.sidebar.number_input("Skin Thickness", min_value=0, max_value=100, value=20)
insulin = st.sidebar.number_input("Insulin", min_value=0, max_value=900, value=85)
bmi = st.sidebar.number_input("BMI", min_value=0.0, max_value=100.0, value=30.0)
diabetes_pedigree = st.sidebar.number_input("Diabetes Pedigree Function", min_value=0.0, max_value=3.0, value=0.5)
age = st.sidebar.number_input("Age", min_value=0, max_value=120, value=45)

patient_data = {
    "pregnancies": pregnancies,
    "glucose": glucose,
    "blood_pressure": blood_pressure,
    "skin_thickness": skin_thickness,
    "insulin": insulin,
    "bmi": bmi,
    "diabetes_pedigree": diabetes_pedigree,
    "age": age
}

if st.sidebar.button("Analyze Health Risk"):
    from agents.health_agent import healthcare_ai_agent, predict_diabetes
    
    risk = predict_diabetes(**patient_data)
    
    if risk.startswith("Model not initialized"):
        st.error(risk)
    else:
        st.subheader("📊 Risk Assessment")
        if risk == "High Diabetes Risk":
            st.error(f"Prediction: {risk}")
        else:
            st.success(f"Prediction: {risk}")
            
        st.subheader("🤖 AI Doctor's Guidance")
        with st.spinner("Generating AI Guidance based on Medical Guidelines..."):
            guidance = healthcare_ai_agent(patient_data)
            st.write(guidance)
