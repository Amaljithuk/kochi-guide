# main.py - PHASE 3: WITH LOCATION-BASED SERVICES

import os
import logging
import json
import requests
import google.generativeai as genai
from dotenv import load_dotenv
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

# --- 1. Configuration and Setup ---
load_dotenv()
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# --- API Keys ---
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
OPENWEATHER_API_KEY = os.getenv("OPENWEATHER_API_KEY")
GOOGLE_PLACES_API_KEY = os.getenv("GOOGLE_PLACES_API_KEY") # NEW

if not all([GEMINI_API_KEY, TELEGRAM_BOT_TOKEN, OPENWEATHER_API_KEY, GOOGLE_PLACES_API_KEY]):
    logger.error("FATAL: One or more API keys are missing from the .env file!")
    exit()

genai.configure(api_key=GEMINI_API_KEY)

# --- 2. Tool Definitions (Functions) ---

def get_kochi_weather():
    # ... (same as before, no changes needed)
    logger.info("Executing tool: get_kochi_weather...")
    base_url = "http://api.openweathermap.org/data/2.5/weather"
    params = {"q": "Kochi,IN", "appid": OPENWEATHER_API_KEY, "units": "metric"}
    try:
        response = requests.get(base_url, params=params)
        response.raise_for_status()
        data = response.json()
        weather_info = {"temperature": data["main"]["temp"], "humidity": data["main"]["humidity"], "description": data["weather"][0]["description"]}
        return json.dumps(weather_info)
    except requests.exceptions.RequestException as e:
        logger.error(f"Error fetching weather: {e}")
        return json.dumps({"error": "Could not fetch weather data."})

# NEW: Tool for finding nearby places
def find_nearby_places(latitude: float, longitude: float, place_type: str):
    """
    Finds nearby places of a specific type (e.g., 'cafe', 'restaurant', 'atm')
    around a given latitude and longitude using the Google Places API.
    """
    logger.info(f"Executing tool: find_nearby_places for {place_type} at ({latitude}, {longitude})")
    base_url = "https://maps.googleapis.com/maps/api/place/nearbysearch/json"
    params = {
        "location": f"{latitude},{longitude}",
        "radius": 1500,  # Search within a 1.5 km radius
        "type": place_type.lower(),
        "key": GOOGLE_PLACES_API_KEY
    }
    try:
        response = requests.get(base_url, params=params)
        response.raise_for_status()
        data = response.json()

        # Extract and simplify the results for the AI model
        places = []
        for place in data.get("results", [])[:5]: # Get top 5 results
            places.append({
                "name": place.get("name"),
                "rating": place.get("rating", "N/A"),
                "address": place.get("vicinity", "No address available")
            })
        return json.dumps(places)
    except requests.exceptions.RequestException as e:
        logger.error(f"Error fetching places from Google API: {e}")
        return json.dumps({"error": "Sorry, I could not find nearby places at the moment."})


# --- 3. Agent Persona and Model Configuration ---
SYSTEM_PROMPT = """
You are 'Kochi Guide', a friendly and enthusiastic local guide for Kochi, Kerala. 
Your personality is warm, helpful, and you know all the local secrets.
If a user asks about places 'near me' or similar, and their location is known, you MUST use the `find_nearby_places` tool.
For weather questions, you MUST use the `get_kochi_weather` tool.
Do not guess or use your training data for real-time information.
When presenting a list of places, format it nicely for the user.
"""

# MODIFIED: Add the new tool to the model's awareness
AGENT_MODEL = genai.GenerativeModel(
    model_name='gemini-1.5-flash',
    system_instruction=SYSTEM_PROMPT,
    tools=[get_kochi_weather, find_nearby_places] # Add the new tool here
)

# --- 4. Telegram Bot Handlers ---
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # (same as before)
    user_name = update.effective_user.first_name; await update.message.reply_text(f"Namaste {user_name}! 👋 I'm your personal guide to Kochi. Share your location with me to find cool places nearby, or ask me anything about the city!")

async def reset_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # (same as before)
    context.user_data.clear(); await update.message.reply_text("Okay, let's start a fresh conversation!")

# NEW: Handler specifically for location messages
async def handle_location(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Saves the user's location when they share it."""
    location = update.message.location
    lat, lon = location.latitude, location.longitude
    logger.info(f"Received location from {update.effective_user.first_name}: ({lat}, {lon})")

    # Store location in user_data, which is persistent per user.
    context.user_data['latitude'] = lat
    context.user_data['longitude'] = lon

    await update.message.reply_text(
        "Thanks, I've got your location! Now, what are you looking for near you? "
        "\n(e.g., 'Find me a good cafe' or 'any ATMs nearby?')"
    )

# MODIFIED: The main message handler is now location-aware
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_message = update.message.text
    chat_id = update.effective_chat.id
    logger.info(f"Received message from chat_id {chat_id}: '{user_message}'")
    await context.bot.send_chat_action(chat_id=chat_id, action='typing')

    try:
        # Check if we have the user's location saved
        lat = context.user_data.get('latitude')
        lon = context.user_data.get('longitude')
        
        prompt = user_message
        if lat and lon:
            # If we have a location, add it to the prompt for the AI
            prompt = f"The user is at location (latitude={lat}, longitude={lon}) and is asking: '{user_message}'"
            logger.info("Injecting location into the prompt.")

        chat_session = AGENT_MODEL.start_chat(enable_automatic_function_calling=True)
        response = await chat_session.send_message_async(prompt)
        ai_response_text = response.text
        
        await update.message.reply_text(ai_response_text)

    except Exception as e:
        logger.error(f"Error in handle_message for {chat_id}: {e}")
        await update.message.reply_text("Sorry, an error occurred. Please try again.")

# --- 5. Main Application Entry Point ---
def main():
    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("reset", reset_command))
    
    # NEW: Add the handler for location messages
    application.add_handler(MessageHandler(filters.LOCATION, handle_location))
    
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    
    logger.info("Kochi Guide Bot (with Location Services) is starting up...")
    application.run_polling()

if __name__ == '__main__':
    main()
