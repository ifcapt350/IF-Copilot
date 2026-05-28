import os
os.system("playwright install chromium")

import streamlit as st
from playwright.sync_api import sync_playwright
import json
from groq import Groq
import shutil

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

# --- TOOL 1: THE FLIGHT SCRAPER ---
def scrape_and_extract_flights(username, status_console):
    raw_page_text = ""
    chrome_path = shutil.which("chromium") or shutil.which("chromium-browser")
    
    with sync_playwright() as p:
        status_console.info("📡 Booting up radar systems...")
        try:
            if chrome_path:
                browser = p.chromium.launch(headless=True, executable_path=chrome_path, args=["--no-sandbox", "--disable-dev-shm-usage", "--disable-gpu"])
            else:
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

    status_console.info("🧠 Telemetry secured. Groq AI is decoding the fleet data...")
    
    # ANTI-HALLUCINATION UPDATE 1: Explicit mapping for the extractor
    extraction_prompt = f"""
    Look at this text scraped from an aviation tracking website for the user '{username}'.
    Extract the data for EVERY SINGLE FLIGHT found into a JSON list containing one dictionary per aircraft.
    Return ONLY a valid JSON list. Do NOT use markdown formatting.
    
    Include these exact keys: "callsign", "aircraft", "livery", "route", "time_to_destination", "time_to_tod", "eta", "cruise_altitude" (CRITICAL: Look for the number next to the word 'Cruise:'), "ground_speed" (CRITICAL: Look for the number next to 'Groundspeed:'), and "flight_plan".
    If ANY piece of data is missing, put "Data Unavailable". 
    If no flights are found, return an empty list: []
    
    Messy Text: {raw_page_text}
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
        return []


# --- TOOL 2: AUTONOMOUS ATC/ATIS SCANNER ---
def scrape_atis_data(airport_code, status_console):
    chrome_path = shutil.which("chromium") or shutil.which("chromium-browser")
    raw_text = ""
    
    with sync_playwright() as p:
        status_console.info(f"📻 Tuning radios to {airport_code} ATC frequencies...")
        try:
            if chrome_path:
                browser = p.chromium.launch(headless=True, executable_path=chrome_path, args=["--no-sandbox", "--disable-dev-shm-usage", "--disable-gpu"])
            else:
                browser = p.chromium.launch(headless=True, args=["--no-sandbox", "--disable-dev-shm-usage"])
                
            page = browser.new_page()
            page.goto("https://if-flightplan-tools.vercel.app/livestatus", timeout=20000)
            page.wait_for_timeout(4000) 
            
            if page.locator(f"text='{airport_code}'").count() > 0:
                status_console.info(f"✅ Intercepted {airport_code} ATC signals. Decoding ATIS...")
                try:
                    atis_buttons = page.locator("text=ATIS")
                    for i in range(atis_buttons.count()):
                        atis_buttons.nth(i).click(timeout=1000)
                except Exception:
                    pass
                
                page.wait_for_timeout(1500) 
                raw_text = page.locator("body").inner_text()
            else:
                raw_text = f"No active ATC or ATIS found for {airport_code} at this time. The airport is uncontrolled."
                
        except Exception as e:
            raw_text = f"ATC Communication Error: {e}"
        finally:
            if 'browser' in locals():
                browser.close()
                
    return raw_text


# --- 4. THE APP UI ---
st.title("✈️ Infinite Flight AI Tracker")

username = st.text_input("Enter IF Username to track:", "Capt350")

if st.button("Search Radar (Live Scan)"):
    status_console = st.empty()
    st.session_state.flights = scrape_and_extract_flights(username, status_console)
    st.session_state.has_searched = True
    status_console.empty() 
    st.session_state.messages = [] 

st.divider()

# --- 5. PERSISTENT UI & CHAT LOGIC ---
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

            flight_context = "\n".join([f"{str(key).title()}: {str(value)}" for key, value in active_flight_data.items()])
            
            # ANTI-HALLUCINATION UPDATE 2: Strict rules for the Chatbot
            system_context = f"""You are an expert aviation co-pilot. You are assisting a pilot in a flight simulator.
            Here is the LIVE RADAR DATA for their current flight: {flight_context}
            
            YOUR CAPABILITIES AND RULES:
            1. ABSOLUTE MANDATE ON NUMBERS: If the user asks for their speed, altitude, ETA, or any other flight statistic, you MUST quote the exact number from the radar data above. DO NOT GUESS. DO NOT invent standard numbers like 34,000. If the data says "Data Unavailable", explicitly tell the user that the instrument is offline or unavailable.
            2. ATC/ATIS RADAR: If the user asks about active ATC, open frequencies, ATIS, or landing/departing runways at ANY specific airport, you MUST trigger the ATC radar tool by replying ONLY with: [FETCH_ATC: ICAO] (e.g., [FETCH_ATC: EGLL]). 
            3. ICAO DECODING: You have full permission to translate 4-letter ICAO codes into real-world airport names using your internal knowledge.
            """
            
            full_prompt = f"{system_context}\n\nPilot's Command/Question: {prompt}"
            
            with st.spinner("Consulting Quick Reference Handbook..."):
                try:
                    response = client.chat.completions.create(
                        messages=[{"role": "user", "content": full_prompt}],
                        model="llama-3.3-70b-versatile",
                        temperature=0.1, # Turning the creativity dial almost to zero so it stops making things up
                    )
                    reply_text = response.choices[0].message.content
                except Exception as e:
                    reply_text = f"⚠️ RADIO FAILURE: API connection error. ({e})"
            
            if "[FETCH_ATC:" in reply_text:
                try:
                    icao_code = reply_text.split("[FETCH_ATC:")[1].split("]")[0].strip().upper()
                    with st.chat_message("assistant"):
                        st.markdown(f"📻 *Requesting ATC telemetry for {icao_code}... standby.*")
                    st.session_state.messages.append({"role": "assistant", "content": f"📻 *Requesting ATC telemetry for {icao_code}... standby.*"})
                    
                    status_console = st.empty()
                    scraped_atc_data = scrape_atis_data(icao_code, status_console)
                    status_console.empty()
                    
                    follow_up_prompt = f"""Here is the LIVE ATC/ATIS DATA scraped from the server for {icao_code}:
                    
                    {scraped_atc_data}
                    
                    Based ONLY on this data, answer the pilot's original question: '{prompt}'. 
                    CRITICAL: If the data shows the airport is staffed but the ATIS text is blank/missing, explicitly state that ATIS hasn't been published yet by the controller.
                    """
                    
                    response2 = client.chat.completions.create(
                        messages=[{"role": "user", "content": follow_up_prompt}],
                        model="llama-3.3-70b-versatile",
                        temperature=0.1,
                    )
                    final_reply = response2.choices[0].message.content
                    
                except Exception as e:
                    final_reply = f"⚠️ Failed to decode ATC transmission: {e}"
                
                with st.chat_message("assistant"):
                    st.markdown(final_reply)
                st.session_state.messages.append({"role": "assistant", "content": final_reply})
                
            else:
                with st.chat_message("assistant"):
                    st.markdown(reply_text)
                st.session_state.messages.append({"role": "assistant", "content": reply_text})
