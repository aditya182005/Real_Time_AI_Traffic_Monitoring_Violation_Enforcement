import streamlit as st

st.set_page_config(
    page_title="Traffic Agent",
    page_icon="🚦",
    layout="wide"
)

st.title("AI-Based Smart Traffic Monitoring System")

st.write(
    "AI-powered traffic monitoring using YOLOv8 and ByteTrack."
)

col1, col2, col3 = st.columns(3)

with col1:
    st.metric("Vehicles", 0)

with col2:
    st.metric("Violations", 0)

with col3:
    st.metric("Emergency Vehicles", 0)

st.subheader("Traffic Camera")

st.info("Camera feed will be integrated in Week 2.")