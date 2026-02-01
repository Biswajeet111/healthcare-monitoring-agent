import streamlit as st
from tools.medication_tool import add_medication, get_medications

add_medication("Paracetamol", "500mg", "08:00 AM")
meds = get_medications()
print(meds)