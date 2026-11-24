"""Local UI for the Track B employee operations copilot."""
from uuid import uuid4

import streamlit as st

from copilot.__main__ import DEMO_TURNS
from copilot.equipment import ALLOWANCES, ITEMS
from copilot.runtime import build_copilot, settings

ALLOWANCE_LABELS = {"new_hire": "New-hire stipend", "annual_refresh": "Annual equipment refresh"}
MODE_LABELS = {
    "demo": "Offline handbook demo",
    "chat": "Course model · Sample handbook",
    "live": "Course model · Full handbook",
}

st.set_page_config(page_title="Employee Operations Copilot", page_icon="📘", layout="wide")


@st.cache_resource(show_spinner=False)
def open_copilot(path, mode, telemetry):
    return build_copilot(path, mode, telemetry)


config = settings()
try:
    agent = open_copilot(**config)
except ValueError as exc:
    st.error(str(exc))
    st.stop()
except (OSError, RuntimeError):
    st.error("The copilot could not start. Check the index and course settings in the README.")
    st.stop()

if "session" not in st.session_state:
    st.session_state.session = uuid4().hex
if "responses" not in st.session_state:
    st.session_state.responses = []

session = st.session_state.session

with st.sidebar:
    st.subheader("Workspace")
    st.caption("Employee Operations Copilot · Track B")
    st.write(MODE_LABELS[config["mode"]])
    if st.button("New session", width="stretch"):
        st.session_state.session = uuid4().hex
        st.session_state.responses = []
        st.rerun()
    st.link_button("Project repository", "https://github.com/abhik2712/CapstoneProject", width="stretch")

st.title("Employee Operations Copilot")
st.write("Check an equipment allowance, prepare a draft for review, or find the public handbook policy.")

equipment, handbook, traces = st.tabs(["Equipment reimbursement", "Handbook search", "Run traces"])


def show_source_links(sources):
    if sources:
        with st.expander("Handbook sources"):
            for source in sources:
                st.link_button(source["title"], source["url"])
                st.text(source["text"])


def show_response(response, *, policy_result=False):
    status = response["status"]
    if status == "complete" and policy_result:
        if response["answer_origin"] == "course_model":
            st.caption("AI-generated handbook answer")
        else:
            st.caption("Prepared handbook answer")
        st.text(response["message"])
    elif status == "complete":
        st.success(response["message"])
    elif status in {"clarify", "evidence"}:
        st.info(response["message"])
    else:
        st.warning(response["message"])
    if response.get("draft"):
        st.code(response["draft"]["text"], language=None, wrap_lines=True)
    show_source_links(response.get("sources"))


def submit_equipment(update):
    st.session_state.responses.append(agent.equipment(session, update))
    st.rerun()


with equipment:
    inputs, results = st.columns([1, 1], gap="large")
    with inputs:
        st.subheader("Purchase details")
        if not st.session_state.responses and st.button("Start $180 monitor example"):
            submit_equipment(DEMO_TURNS[0])
        _, facts = agent.store.load(session)
        if facts.item is None:
            with st.form("purchase"):
                item = st.selectbox("Item", ITEMS, index=None, placeholder="Choose equipment")
                st.caption("Monitor refers to a standard monitor.")
                price = st.text_input("Purchase price (USD)", placeholder="180.00")
                credits = st.text_input("Gift cards and other credits (USD)", value="0")
                draft = st.checkbox("Prepare a draft once the estimate is ready", value=True)
                if st.form_submit_button("Continue", type="primary"):
                    submit_equipment({"item": item, "price": price, "credits": credits, "draft": draft})
        else:
            st.write(f"{facts.item.title()} · USD {facts.price} purchase · USD {facts.credits} in credits")
            field, prompt = facts.next_question()
            if field == "allowance":
                with st.form("allowance"):
                    allowance = st.radio(prompt, list(ALLOWANCES), format_func=ALLOWANCE_LABELS.get, index=None)
                    if st.form_submit_button("Continue", type="primary"):
                        submit_equipment({"allowance": allowance})
            elif field == "eligible":
                with st.form("eligibility"):
                    eligible = st.radio(prompt, (True, False), format_func=lambda value: "Yes" if value else "No", index=None)
                    if st.form_submit_button("Continue", type="primary"):
                        submit_equipment({"eligible": eligible})
            elif field == "remaining":
                with st.form("balance"):
                    balance = st.text_input(prompt, placeholder="200.00")
                    if st.form_submit_button("Calculate", type="primary"):
                        submit_equipment({"remaining": balance})
            elif not field and facts.eligible and not facts.draft:
                if st.button("Prepare draft", type="primary"):
                    submit_equipment({"draft": True})

    with results:
        st.subheader("Copilot responses")
        if st.session_state.responses:
            for response in reversed(st.session_state.responses[-8:]):
                show_response(response)
        else:
            st.caption("Enter your purchase details to check the policy and estimate a claim.")

with handbook:
    st.subheader("Ask about a public policy")
    if config["mode"] == "demo":
        st.caption("Offline mode shows prepared guidance or source passages. Use course chat mode for AI-generated answers.")
    with st.form("handbook"):
        question = st.text_input("Question", placeholder="What should I attach if I lost a receipt?", max_chars=500)
        if st.form_submit_button("Search handbook", type="primary"):
            st.session_state.policy_result = agent.policy(session, question)
            st.session_state.policy_session = session
    if st.session_state.get("policy_session") == session:
        show_response(st.session_state.policy_result, policy_result=True)

with traces:
    st.subheader("Executions in this session")
    rows = agent.store.traces(session)
    if not rows:
        st.caption("Run the copilot to see planner decisions, tool calls, and critic checks.")
    for index, trace in enumerate(rows):
        with st.expander(f"Run {trace['id']} · {trace['outcome'].replace('_', ' ')}", expanded=index == 0):
            steps = trace["steps"]
            total = sum(step["duration_ms"] for step in steps)
            calls = sum(step["stage"] == "executor" and step["operation"] != "course_chat" for step in steps)
            st.caption(f"{len(steps)} steps · {calls} tool calls · {total:.0f} ms in recorded steps")
            if steps:
                st.dataframe(steps, hide_index=True, width="stretch")
