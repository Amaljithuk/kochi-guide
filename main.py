# main.py

import os
import logging
import json
import requests
import google.generativeai as genai
from dotenv import load_dotenv
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

# --- 1. Configuration and Setup ---
# Load environment variables from the .env file
load_dotenv()

# Set up basic logging to see bot activity and errors in the console
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Get API keys from environment variables
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
OPENWEATHER_API_KEY = os.getenv("OPENWEATHER_API_KEY")

# Exit if any essential API key is missing
if not all([GEMINI_API_KEY, TELEGRAM_BOT_TOKEN, OPENWEATHER_API_KEY]):
    logger.error("FATAL: One or more API keys are missing from the .env file!")
    exit()

# Configure the Gemini API client
genai.configure(api_key=GEMINI_API_KEY)

# --- 2. Tool Definition (Function Calling) ---
def get_kochi_weather():
    """
    Gets the current weather in Kochi, Kerala using the OpenWeatherMap API.
    Returns a JSON string with temperature, humidity, and weather description.
    """
    logger.info("Executing tool: get_kochi_weather...")
    base_url = "http://api.openweathermap.org/data/2.5/weather"
    params = {
        "q": "Kochi,IN",
        "appid": OPENWEATHER_API_KEY,
        "units": "metric"  # For temperature in Celsius
    }
    try:
        response = requests.get(base_url, params=params)
        response.raise_for_status()  # Raises an HTTPError for bad responses (4xx or 5xx)
        data = response.json()
        
        # Extracting the relevant weather information
        weather_info = {
            "temperature": data["main"]["temp"],
            "humidity": data["main"]["humidity"],
            "description": data["weather"][0]["description"]
        }
        # Gemini tools expect a JSON string as the return value
        return json.dumps(weather_info)
    except requests.exceptions.RequestException as e:
        logger.error(f"Error fetching weather from API: {e}")
        return json.dumps({"error": "Sorry, I could not fetch the weather data at the moment."})

# --- 3. Agent Persona and Model Configuration ---
SYSTEM_PROMPT = """
You are 'Kochi Guide', a friendly and enthusiastic local guide for Kochi, Kerala.
Your personality is warm, helpful, and you know all the local secrets.
Your goal is to help users discover the best of the city, including its food, history, art, and culture.
When a user asks about the current weather, you MUST use the `get_kochi_weather` tool. Do not guess or use your training data for real-time information.
When giving recommendations, explain WHY a place is special.
If you don't know something, say so honestly.
Keep your answers conversational. You can use a little bit of 'Manglish' (like saying 'ennale?' or 'adipoli!') where it feels natural, but primarily respond in English.
Today is Tuesday, July 29, 2025. It's the middle of the monsoon season, so keep that in mind for your suggestions (e.g., suggest indoor activities).
"""

# Initialize the Generative Model, telling it about the available tool
AGENT_MODEL = genai.GenerativeModel(
    model_name='gemini-2.0-flash',
    system_instruction=SYSTEM_PROMPT,
    tools=[get_kochi_weather]  # Make the model aware of our function
)

# In-memory storage for conversation history, keyed by chat_id
conversation_history = {}


# --- 4. Telegram Bot Handlers ---
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles the /start command. Welcomes the user and resets their conversation history."""
    user_name = update.effective_user.first_name
    chat_id = update.effective_chat.id
    conversation_history[chat_id] = []  # Clear any previous history for this user
    welcome_message = (
        f"Namaste {user_name}! 👋 I'm your personal guide to the beautiful city of Kochi. "
        "Ask me anything about places, food, our culture, or even the current weather!"
    )
    await update.message.reply_text(welcome_message)

async def reset_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles the /reset command. Clears the conversation history for the user."""
    chat_id = update.effective_chat.id
    conversation_history[chat_id] = []
    await update.message.reply_text("Okay, let's start a fresh conversation! What would you like to know?")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """The main message handler. Processes user text and interacts with the Gemini agent."""
    chat_id = update.effective_chat.id
    user_message = update.message.text

    logger.info(f"Received message from chat_id {chat_id}: '{user_message}'")
    
    # Show a "typing..." indicator to the user
    await context.bot.send_chat_action(chat_id=chat_id, action='typing')

    try:
        # Ensure the user has a history list initialized
        if chat_id not in conversation_history:
            conversation_history[chat_id] = []

        # Start a chat session with the model, enabling automatic function calling
        chat_session = AGENT_MODEL.start_chat(
            history=conversation_history[chat_id],
            enable_automatic_function_calling=True
        )

        # Send the user's message to the model
        response = await chat_session.send_message_async(user_message)
        
        # The SDK handles the function call and response automatically. We just get the final text.
        ai_response_text = response.text

        # Update the conversation history with the latest interaction
        conversation_history[chat_id] = chat_session.history
        
        # Send the final, user-facing response back to Telegram
        await update.message.reply_text(ai_response_text)

    except Exception as e:
        logger.error(f"Error in handle_message for chat_id {chat_id}: {e}")
        await update.message.reply_text("Sorry, an error occurred on my end. Please try again in a moment.")


# --- 5. Main Application Entry Point ---
def main():
    """Sets up the Telegram bot and starts polling for messages."""
    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

    # Register the command handlers
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("reset", reset_command))

    # Register the main message handler for all non-command text messages
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    logger.info("Kochi Guide Agent is starting up...")
    
    # Start the bot. It will run until you press Ctrl-C.
    application.run_polling()

if __name__ == '__main__':
    main()