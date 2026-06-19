import streamlit as st
import streamlit.components.v1 as components
import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Set page config
st.set_page_config(
    page_title="MedGraph AI - GraphRAG & Neo4j",
    page_icon="⚕️",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Imports from utils
from graph_utils import (
    get_driver, query_graphrag_context, render_graph_visual, 
    find_candidate_diseases, get_next_clarifying_symptom, render_patient_history_visual
)
from llm_utils import (
    extract_symptoms, generate_explanation, analyze_response,
    generate_consultation_summary, generate_patient_greeting
)
from data_setup import setup_database
from memory_utils import save_consultation, detect_chronic_conditions, get_patient_history


# Custom CSS for modern look
st.markdown("""
<style>
    .reportview-container {
        background: #0E1117;
    }
    .disease-card {
        padding: 15px;
        border-radius: 10px;
        border-left: 5px solid #FF4B4B;
        background-color: #1E293B;
        margin-bottom: 10px;
    }
    .symptom-tag {
        display: inline-block;
        padding: 2px 10px;
        border-radius: 15px;
        background-color: #F1A70A;
        color: black;
        font-weight: bold;
        margin-right: 5px;
        font-size: 0.8em;
    }
    .ruled-out-tag {
        display: inline-block;
        padding: 2px 10px;
        border-radius: 15px;
        background-color: #64748B;
        color: white;
        font-weight: bold;
        margin-right: 5px;
        font-size: 0.8em;
    }
</style>
""", unsafe_allow_html=True)

# App Title & Description
st.title("⚕️ MedGraph AI: Interactive Doctor")
st.markdown("### *A conversational clinical agent powered by Neo4j GraphRAG & Groq Llama 3.*")

# Initialize Session States
if "driver" not in st.session_state:
    st.session_state.driver = get_driver()

if "patient_id" not in st.session_state:
    st.session_state.patient_id = "Patient_001"

if "patient_history" not in st.session_state:
    st.session_state.patient_history = {"chronic_conditions": [], "consultations": []}
    if st.session_state.driver:
        st.session_state.patient_history = get_patient_history(st.session_state.driver, st.session_state.patient_id)

def fetch_all_symptoms(driver):
    if not driver:
        return []
    query = "MATCH (s:Symptom) RETURN s.name as name ORDER BY name"
    try:
        with driver.session() as session:
            res = session.run(query)
            return [r['name'] for r in res]
    except Exception as e:
        print(f"Error fetching symptoms: {e}")
        return []

if "all_symptoms" not in st.session_state:
    st.session_state.all_symptoms = fetch_all_symptoms(st.session_state.driver)
    if not st.session_state.all_symptoms:
        st.session_state.all_symptoms = [
            "Fever", "Cough", "Fatigue", "Vomiting", "Nausea", "Dizziness", "Chest Pain", 
            "Shortness Of Breath", "Headache", "Runny Nose", "Itching", "Skin Rash", 
            "Joint Pain", "Muscle Pain", "Chills", "Loss Of Appetite", "Diarrhoea", 
            "Abdominal Pain"
        ]

# Reset consultation state helper
def reset_consultation():
    history = st.session_state.get("patient_history", {"chronic_conditions": [], "consultations": []})
    patient_id = st.session_state.get("patient_id", "Patient_001")
    
    greeting = generate_patient_greeting(patient_id, history)
    
    st.session_state.messages = [{
        "role": "assistant",
        "content": greeting
    }]
    st.session_state.confirmed_symptoms = set()
    st.session_state.ruled_out_symptoms = set()
    st.session_state.stage = "waiting_init"
    st.session_state.question_count = 0
    st.session_state.current_question_symptom = None
    st.session_state.questions_asked = []
    st.session_state.saved_to_memory = False

# Initialize consultation states
if "messages" not in st.session_state:
    reset_consultation()


# Sidebar Configuration
with st.sidebar:
    st.image("https://neo4j.com/wp-content/themes/neo4j/assets/images/neo4j-logo-2020.svg", width=150)
    st.header("⚙️ Configuration")
    
    # Environment Statuses
    neo4j_ready = st.session_state.driver is not None
    groq_ready = os.getenv("GROQ_API_KEY") is not None
    
    if neo4j_ready:
        st.success("✅ Neo4j Connection: Active")
    else:
        st.error("❌ Neo4j Connection: Failed")
        
    if groq_ready:
        st.success("✅ Groq Client: Active")
    else:
        st.warning("⚠️ Groq Client: Not Configured")

    st.divider()
    st.subheader("👤 Patient Profile Selection")
    new_patient_id = st.text_input("Patient ID / Name", value=st.session_state.patient_id)
    if new_patient_id != st.session_state.patient_id:
        st.session_state.patient_id = new_patient_id
        if st.session_state.driver:
            st.session_state.patient_history = get_patient_history(st.session_state.driver, new_patient_id)
        reset_consultation()
        st.rerun()

    # Display dynamic summary of history in the sidebar
    if st.session_state.patient_history:
        history = st.session_state.patient_history
        num_past = len(history.get("consultations", []))
        st.info(f"📁 Past Consultations: **{num_past}**")
        
        chronic = history.get("chronic_conditions", [])
        if chronic:
            st.warning(f"⚠️ Chronic Conditions: **{', '.join(chronic)}**")

    st.divider()
    st.subheader("🛠️ Setup & Demo Tools")
    
    # Button to populate DB
    if st.button("Initialize & Populate Knowledge Graph", use_container_width=True):
        if not neo4j_ready:
            st.error("Cannot populate database: Neo4j is not connected.")
        else:
            with st.spinner("Populating knowledge graph..."):
                try:
                    setup_database()
                    st.session_state.all_symptoms = fetch_all_symptoms(st.session_state.driver)
                    st.success("Knowledge Graph successfully populated!")
                except Exception as e:
                    st.error(f"Failed to populate: {e}")
                    
    st.divider()
    st.markdown("""
    **Demo 1 Input:**
    `I have shivering and continuous sneezing`
    
    **Demo 2 Input:**
    `I have stomach pain and acidity`
    """)

# Core functions for processing steps
def process_initial_input(user_text):
    st.session_state.messages.append({"role": "user", "content": user_text})
    
    with st.spinner("Extracting symptoms..."):
        extracted = extract_symptoms(user_text, st.session_state.all_symptoms)
        
    if not extracted:
        st.session_state.messages.append({
            "role": "assistant",
            "content": "I couldn't identify any specific symptoms from that description. Could you please specify where it hurts or describe it differently?"
        })
    else:
        st.session_state.confirmed_symptoms.update(extracted)
        st.session_state.stage = "clarifying"
        
        candidates = find_candidate_diseases(st.session_state.driver, st.session_state.confirmed_symptoms)
        next_symptom = get_next_clarifying_symptom(
            st.session_state.driver, 
            st.session_state.confirmed_symptoms, 
            st.session_state.ruled_out_symptoms, 
            candidates
        )
        
        if next_symptom:
            st.session_state.current_question_symptom = next_symptom
            st.session_state.messages.append({
                "role": "assistant",
                "content": f"I've noted: **{', '.join(extracted)}**. To help narrow down the diagnosis, are you experiencing any **{next_symptom}**?"
            })
        else:
            st.session_state.stage = "diagnosed"
            st.session_state.messages.append({
                "role": "assistant",
                "content": "I have completed my assessment. You can review the final diagnosis and graph reasoning on the right."
            })

def process_clarification(btn_val, text_val):
    current_sym = st.session_state.current_question_symptom
    st.session_state.questions_asked.append(current_sym)
    
    if btn_val is not None:
        if btn_val:
            st.session_state.confirmed_symptoms.add(current_sym)
            st.session_state.messages.append({"role": "user", "content": f"Yes, I have {current_sym}."})
        else:
            st.session_state.ruled_out_symptoms.add(current_sym)
            st.session_state.messages.append({"role": "user", "content": f"No, I don't have {current_sym}."})
    else:
        st.session_state.messages.append({"role": "user", "content": text_val})
        with st.spinner("Analyzing response..."):
            analysis = analyze_response(text_val, current_sym, st.session_state.all_symptoms)
        
        if analysis.get("confirmed") is True:
            st.session_state.confirmed_symptoms.add(current_sym)
        elif analysis.get("confirmed") is False:
            st.session_state.ruled_out_symptoms.add(current_sym)
            
        for add_sym in analysis.get("additional_symptoms", []):
            st.session_state.confirmed_symptoms.add(add_sym)
            
    st.session_state.question_count += 1
    
    candidates = find_candidate_diseases(st.session_state.driver, st.session_state.confirmed_symptoms)
    next_symptom = get_next_clarifying_symptom(
        st.session_state.driver,
        st.session_state.confirmed_symptoms,
        st.session_state.ruled_out_symptoms,
        candidates
    )
    
    if st.session_state.question_count >= 3 or not next_symptom or not candidates:
        st.session_state.stage = "diagnosed"
        st.session_state.current_question_symptom = None
        st.session_state.messages.append({
            "role": "assistant",
            "content": "Thank you for the clarification. I have completed my analysis. You can review the final diagnosis and explanation on the right."
        })
    else:
        st.session_state.current_question_symptom = next_symptom
        st.session_state.messages.append({
            "role": "assistant",
            "content": f"Got it. Are you also experiencing any **{next_symptom}**?"
        })

# Two-Column Layout: Left for active Doctor dialogue, Right for real-time Reasoning Path
col1, col2 = st.columns([1, 1])

with col1:
    st.subheader("💬 Doctor Consultation Chat")
    
    # Render chat bubble container
    chat_container = st.container(height=500)
    with chat_container:
        for msg in st.session_state.messages:
            with st.chat_message(msg["role"]):
                st.markdown(msg["content"])
                
    # Quick Action Buttons for clarifying question
    if st.session_state.stage == "clarifying" and st.session_state.current_question_symptom:
        st.markdown(f"**Do you have {st.session_state.current_question_symptom}?**")
        btn_col1, btn_col2 = st.columns(2)
        if btn_col1.button("🟢 Yes, I do", key="btn_yes", use_container_width=True):
            process_clarification(True, "")
            st.rerun()
        if btn_col2.button("🔴 No, I don't", key="btn_no", use_container_width=True):
            process_clarification(False, "")
            st.rerun()
            
    # Chat inputs
    if st.session_state.stage != "diagnosed":
        user_msg = st.chat_input("Reply to the doctor here...")
        if user_msg:
            if st.session_state.stage == "waiting_init":
                process_initial_input(user_msg)
            elif st.session_state.stage == "clarifying":
                process_clarification(None, user_msg)
            st.rerun()
    else:
        if st.button("🔄 Start New Consultation", use_container_width=True):
            reset_consultation()
            st.rerun()

with col2:
    tab1, tab2 = st.tabs(["🕸️ Live GraphRAG Reasoning", "👤 Patient Health Timeline"])
    
    with tab1:
        # Show current state stats
        if st.session_state.confirmed_symptoms:
            st.markdown("**Confirmed Symptoms:**")
            conf_html = "".join([f'<span class="symptom-tag">{s}</span>' for s in st.session_state.confirmed_symptoms])
            st.markdown(conf_html, unsafe_allow_html=True)
            
            if st.session_state.ruled_out_symptoms:
                st.markdown("**Ruled Out Symptoms:**")
                rule_html = "".join([f'<span class="ruled-out-tag">{s}</span>' for s in st.session_state.ruled_out_symptoms])
                st.markdown(rule_html, unsafe_allow_html=True)
                
            st.write("")
            
            # Real-time Query to Neo4j Graph
            context = query_graphrag_context(st.session_state.driver, list(st.session_state.confirmed_symptoms))
            
            if context:
                # Save consultation if final diagnosis achieved and not yet saved
                if st.session_state.stage == "diagnosed" and not st.session_state.get("saved_to_memory", False):
                    top_match = context[0]
                    num_symptoms_matched = len(top_match['matched_symptoms'])
                    confidence = min(num_symptoms_matched * 25, 99)
                    
                    with st.spinner("Saving consultation to patient memory graph..."):
                        summary = generate_consultation_summary(st.session_state.confirmed_symptoms, top_match['disease'])
                        metadata = {
                            "severity": "Moderate",
                            "confidence_score": confidence,
                            "llm_summary": summary
                        }
                        save_consultation(
                            st.session_state.driver,
                            st.session_state.patient_id,
                            st.session_state.confirmed_symptoms,
                            top_match['disease'],
                            metadata
                        )
                        detect_chronic_conditions(st.session_state.driver, st.session_state.patient_id)
                        st.session_state.patient_history = get_patient_history(st.session_state.driver, st.session_state.patient_id)
                        st.session_state.saved_to_memory = True
                    st.rerun()

                # Interactive Graph
                st.markdown("**Real-time Graph Traversal Visualization:**")
                graph_html = render_graph_visual(context)
                if graph_html:
                    components.html(graph_html, height=350)
                
                # If final diagnosis achieved, show explanation & breakdown
                if st.session_state.stage == "diagnosed":
                    st.markdown("### ✨ Doctor's assessment & Explanation")
                    with st.spinner("Formulating doctor assessment..."):
                        explanation = generate_explanation(st.session_state.confirmed_symptoms, context, st.session_state.patient_history)
                        st.write(explanation)
                        
                    st.markdown("### 🎯 GraphRAG Reasoning Breakdown")
                    top_match = context[0]
                    st.markdown(f"<div class='disease-card'><h4>Assessment: <b>{top_match['disease']}</b></h4>", unsafe_allow_html=True)
                    
                    if top_match.get('category'):
                        st.markdown(f"✓ Disease Category: **{top_match['category']}**")
                        
                    for sym in top_match['matched_symptoms']:
                        st.markdown(f"✓ **{sym}** matched (found `:INDICATES` relation)")
                        
                    if top_match.get('precautions'):
                        st.markdown(f"✓ Recommended precautions: **{', '.join(top_match['precautions'][:3])}**")
                        
                    if top_match['specialists'] and top_match['specialists'][0]:
                        st.markdown(f"✓ Specialist: **{', '.join(top_match['specialists'])}** (found `:CONSULT` relation)")
                        
                    if top_match['medicines'] and top_match['medicines'][0]:
                        st.markdown(f"✓ Medicine: **{', '.join(top_match['medicines'])}** (found `:TREATED_BY` relation)")
                        
                    # Confidence score based on percentage of matching symptoms
                    num_symptoms_matched = len(top_match['matched_symptoms'])
                    confidence = min(num_symptoms_matched * 25, 99)
                    st.markdown(f"✓ **Graph-based Confidence Score:** `{confidence}%` ({num_symptoms_matched} symptom matches)")
                    st.markdown("</div>", unsafe_allow_html=True)
                else:
                    # Show live candidates
                    st.markdown("### 📋 Current Suspected Conditions:")
                    for candidate in context[:3]:
                        match_count = len(candidate['matched_symptoms'])
                        st.markdown(f"**{candidate['disease']}** (matches: {', '.join(candidate['matched_symptoms'])})")
                        st.progress(min(match_count / 5.0, 1.0))
            else:
                st.info("No matching conditions in the knowledge graph yet.")
        else:
            st.info("Waiting for symptom entry on the left to activate Neo4j Graph traversal...")

    with tab2:
        st.subheader("Patient Long-Term Memory")
        history = st.session_state.get("patient_history", {"chronic_conditions": [], "consultations": []})
        
        if history and history.get("consultations"):
            st.markdown(f"**Visualizing medical history for {st.session_state.patient_id}:**")
            history_html = render_patient_history_visual(history, st.session_state.patient_id)
            if history_html:
                components.html(history_html, height=350)
                
            st.markdown("### Previous Consultations:")
            for idx, c in enumerate(history.get("consultations", [])):
                with st.expander(f"📅 Consultation - {c.get('date', 'Unknown Date')} ({c.get('diagnosis', 'Unknown')})", expanded=(idx==0)):
                    st.markdown(f"**Resulting Diagnosis:** `{c.get('diagnosis')}`")
                    st.markdown(f"**Severity:** `{c.get('severity')}` | **Confidence:** `{c.get('confidence_score')}%`")
                    st.markdown(f"**Confirmed Symptoms:** {', '.join(c.get('symptoms', []))}")
                    st.markdown(f"**Clinical Summary:** *{c.get('llm_summary')}*")
        else:
            st.info("No history recorded for this patient yet. Complete a consultation to start building their history!")

