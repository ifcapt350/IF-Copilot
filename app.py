import streamlit as st
from playwright.sync_api import sync_playwright
import json
from groq import Groq
import shutil
import os

# 1. Setup the Engine (Securely using Streamlit Secrets)
try:
    client = Groq(api_key=st.secrets["GROQ_API_KEY"])
except Exception:
    st.error("⚠️ Radar Offline: GROQ_API_KEY is missing from Streamlit Secrets.")
    st.stop()

# 2. Bulletproof State Management
if "has_searched" not in st.session_state:
    st.session_state.has_searched = False
if "flights" not in st.session_state:
    st.session_state.flights = []
if "messages" not in st.session_state:
    st.session_state.messages = []

# 3. The Live Scraper (Native Cloud Version)
def scrape_and_extract_flights(username, status_console):
    raw_page_text = ""
    
    # THE FIX: Hunt down the native Linux Chromium browser
    chrome_path = shutil.which("chromium") or shutil.which("chromium-browser")
    
    with sync_playwright() as p:
        status_console.info("📡 Booting up radar systems...")
        
        try:
            # Launch using the ultra-light native browser
            if chrome_path:
                browser = p.chromium.launch(headless=True, executable_path=chrome_path, args=["--no-sandbox", "--disable-dev-shm-usage", "--disable-gpu"])
            else:
                # Fallback if it can't find it
                browser = p.chromium.launch(headless=True, args=["--no-sandbox", "--disable-dev-shm-usage"])
                
            page = browser.new_page()
            raw_pages = [] 
            
            status_console.info(f"🛰️ Pinging IF servers for callsign: {username}...")
            page.goto("https://if-flightplan-tools.vercel.app/flightstatus", timeout=20000)
            page.locator("label:has-text('Username:') + input").fill(username)
            page.locator("#startSearch").click()
            
            status_console.info("⏳ Waiting for transponder response...")
            page.wait_for_timeout(4000) 
            
            flight_dropdown = page.locator("select").nth(1)
            option_count = flight_dropdown.locator("option").count()
            if option_count == 0: option_count = 1
                
            status_console.info(f"✈️ Detected {option_count} aircraft. Downloading telemetry...")
            for i in range(option_count):
                try:
                    if flight_dropdown.locator("option").count() > 0:
                        flight_dropdown.select_option(index=i)
                        
                    page.locator("button:has-text('Get Status')").click()
                    page.wait_for_timeout(2500) 
                    
                    try:
                        page.locator("button:has-text('Open FlightPlan')").click(timeout=2000)
                        page.wait_for_timeout(6000) 
                        
                        page.evaluate('''
                            const inputs = document.querySelectorAll('input');
                            for (let i = 0; i < inputs.length; i++) {
                                if (inputs[i].value && inputs[i].value.trim() !== '') {
                                    const textNode = document.createTextNode(' [' + inputs[i].value + '] ');
                                    inputs[i].parentNode.replaceChild(textNode, inputs[i]);
                                }
                            }
                        ''')
                        page.wait_for_timeout(500)
                    except Exception:
                        pass 
                        
                    raw_pages.append(page.locator("body").inner_text())
                except Exception:
                    pass
                    
            raw_page_text = "\n\n=== NEXT AIRCRAFT ===\n\n".join(raw_pages)
            
        except Exception as e:
            st.error(f"Radar malfunction or Tracker Website Timeout: {e}")
            return []
        finally:
            if 'browser' in locals():
                browser.close()

    # --- PHASE B: Groq 3.3 Data Extraction ---
    status_console.info("🧠 Telemetry secured. Groq AI is decoding the fleet data...")
    extraction_prompt = f"""
    Look at this text scraped from an aviation tracking website for the user '{username}'.
    CRITICAL INSTRUCTION: There may be MULTIPLE active flights in this text, separated by '=== NEXT AIRCRAFT ==='. 
    You MUST extract the data for EVERY SINGLE FLIGHT found.
    
    Extract them into a JSON list containing one dictionary per aircraft.
    Return ONLY a valid JSON list. Do NOT use markdown formatting.
    Include these keys for each dictionary: "callsign", "aircraft", "livery", "route", "time_to_destination", "time_to_tod", "eta", "cruise_altitude", "ground_speed", and "flight_plan".
    If ANY piece of data is missing, put "Data Unavailable". 
    If no flights are found, return an empty list: []
    
    Messy Text:
    {raw_page_text}
    """
    
    try:
        extraction_response = client.chat.completions.create(
            messages=[{"role": "user", "content": extraction_prompt}],
            model="llama-3.3-70b-versatile",
            temperature=0, 
        )
        
        raw_ai_text = extraction_response.choices[0].message.content.strip()
        
        raw_ai_text = raw_ai_text.strip("` \n")
        if raw_ai_text.lower().startswith("json"):
            raw_ai_text = raw_ai_text[4:].strip("` \n")
            
        flights_list = json.loads(raw_ai_text)
        
        if isinstance(flights_list, dict):
            flights_list = [] if not flights_list else [flights_list]
        return flights_list
        
    except Exception as e:
        st.error(f"Radar Comms Failure (Groq JSON Parsing): {e}")
        return []

# 4. The App UI
st.title("✈️ Custom IF Co-Pilot v17 (Native Cloud)")

username = st.text_input("Enter IF Username to track:", "Capt350")

if st.button("Search Radar (Live Scan)"):
    status_console = st.empty()
    st.session_state.flights = scrape_and_extract_flights(username, status_console)
    st.session_state.has_searched = True
    status_console.empty() 
    st.session_state.messages = [] 

st.divider()

# 5. Persistent UI Logic
if st.session_state.has_searched:
    if len(st.session_state.flights) == 0:
        st.warning("⚠️ Radar sweep complete, but no active flights were found for this username.")
    else:
        st.success(f"Found {len(st.session_state.flights)} active flight(s) in the system!")
        
        flight_options = {}
        for index, f in enumerate(st.session_state.flights):
            aircraft = f.get('aircraft', 'Unknown Aircraft')
            callsign = f.get('callsign', 'Unknown')
            route = f.get('route', 'Data Unavailable')
            
            if route in ["Data Unavailable", "", "Unknown Route"]:
                display_label = f"[{index + 1}] {aircraft} {callsign} | (No Route Filed / VFR)"
            else:
                display_label = f"[{index + 1}] {aircraft} {callsign} | {route}"
                
            flight_options[display_label] = f
        
        selected_label = st.selectbox("Select your aircraft:", list(flight_options.keys()))
        active_flight_data = flight_options[selected_label]
        
        st.divider()

        for message in st.session_state.messages:
            with st.chat_message(message["role"]):
                st.markdown(message["content"])

        if prompt := st.chat_input("Ask your Co-Pilot a question (Press Enter to send)..."):
            st.chat_message("user").markdown(prompt)
            st.session_state.messages.append({"role": "user", "content": prompt})

            with st.spinner("Consulting Quick Reference Handbook..."):
                flight_context = "\n".join([f"{str(key).title()}: {str(value)}" for key, value in active_flight_data.items()])
                
                system_context = f"""You are an expert aviation co-pilot. You are assisting a pilot in a flight simulator.
                Here is the LIVE RADAR DATA for their current flight:
                {flight_context}
                
                YOUR CAPABILITIES:
                1. If the user asks about their current flight stats (speed, altitude, eta), answer strictly using the radar data above. 
                2. ICAO DECODING: You have full permission to translate 4-letter ICAO codes (like FACT, KLAX, EGLL) into real-world airport names and cities using your internal knowledge. 
                3. TACTICAL ADVICE: If the user asks for diversion airports or weather, use your internal knowledge to provide real-world options based on their current route.
                4. CRITICAL: Do not invent fake airports. If you genuinely do not recognize an ICAO code, just state the 4-letter code.
                """
                
                full_prompt = f"{system_context}\n\nPilot's Command/Question: {prompt}"
                
                try:
                    response = client.chat.completions.create(
                        messages=[{"role": "user", "content": full_prompt}],
                        model="llama-3.3-70b-versatile",
                    )
                    reply_text = response.choices[0].message.content
                except Exception as e:
                    reply_text = f"⚠️ RADIO FAILURE: API connection error. ({e})"
                
            with st.chat_message("assistant"):
                st.markdown(reply_text)
            st.session_state.messages.append({"role": "assistant", "content": reply_text})
