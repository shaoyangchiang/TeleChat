# -*- coding: utf-8 -*-
"""v1 (1).ipynb

Automatically generated by Colab.

Original file is located at
    https://colab.research.google.com/drive/1JNL6KaSF3cDR812axC3_meMab8j_nsXe
"""

from google.colab import drive
drive.mount('/content/drive')

!pip install python-telegram-bot pandas faiss-cpu numpy sentence-transformers openai python-dotenv firebase-admin nest_asyncio

import nest_asyncio
nest_asyncio.apply()


import os
import openai
import firebase_admin
from firebase_admin import credentials, firestore
from dotenv import load_dotenv

# Load environment variables

import os
import openai
import firebase_admin
from firebase_admin import credentials, firestore
from dotenv import load_dotenv

# ✅ Load environment variables (Railway will provide them)
openai_api_key = os.getenv("OPENAI_API_KEY")
telegram_token = os.getenv("TELEGRAM_BOT_TOKEN")
firebase_cred_json = os.getenv("FIREBASE_CREDENTIALS_JSON")  # Railway stores JSON as a string

# ✅ Check if all required environment variables are available
if not all([openai_api_key, telegram_token, firebase_cred_json]):
    raise ValueError("❌ Missing API keys in Railway environment variables!")

print("✅ API Keys Loaded Successfully!")

# ✅ Initialize Firebase using the credentials stored in Railway
if not firebase_admin._apps:
    import json
    firebase_creds = json.loads(firebase_cred_json)  # Convert JSON string to dictionary
    cred = credentials.Certificate(firebase_creds)
    firebase_admin.initialize_app(cred)

db = firestore.client()
print("✅ Connected to Firebase Firestore!")

import os
import pandas as pd
import faiss
import numpy as np
from sentence_transformers import SentenceTransformer

csv_path = "recipe_metadata.csv"
faiss_index_path = "recipe_faiss.index"

if not os.path.exists(csv_path) or not os.path.exists(faiss_index_path):
    print("🔄 Creating FAISS index and metadata CSV...")

    # Load dataset
    dataset_path = "/content/drive/MyDrive/InnovationChallenge/RecipeNLG_dataset.csv"
    df = pd.read_csv(dataset_path, nrows=10000)
    df["text"] = df.apply(lambda row: f"Title: {row['title']}\nIngredients: {row['ingredients']}\nInstructions: {row['directions']}", axis=1)

    # Load embedding model
    model = SentenceTransformer("all-MiniLM-L6-v2")

    # Encode text
    df["embedding"] = df["text"].apply(lambda x: model.encode(x, convert_to_numpy=True))
    embeddings = np.vstack(df["embedding"].values)

    # Create FAISS index
    embedding_dim = embeddings.shape[1]
    index = faiss.IndexFlatL2(embedding_dim)
    index.add(embeddings)

    # Save FAISS index & metadata
    faiss.write_index(index, faiss_index_path)
    df.to_csv(csv_path, index=False)

    print("✅ FAISS index and metadata saved!")

else:
    print("✅ Loading existing FAISS index and metadata...")
    df = pd.read_csv(csv_path)
    index = faiss.read_index(faiss_index_path)
    model = SentenceTransformer("all-MiniLM-L6-v2")

print(f"✅ Loaded {len(df)} recipes!")

def get_user_data(user_id):
    """Retrieve user preferences from Firestore."""
    user_ref = db.collection("users").document(user_id)
    user_doc = user_ref.get()

    return user_doc.to_dict() if user_doc.exists else None

def set_user_data(user_id, data):
    """Save user preferences in Firestore."""
    user_ref = db.collection("users").document(user_id)
    user_ref.set(data, merge=True)  # Merge to avoid overwriting

def get_user_conversation(user_id):
    """Retrieve user conversation history."""
    user_ref = db.collection("conversations").document(user_id)
    user_doc = user_ref.get()

    return user_doc.to_dict().get("messages", []) if user_doc.exists else []

def save_user_conversation(user_id, messages):
    """Save user conversation history to Firestore."""
    user_ref = db.collection("conversations").document(user_id)
    user_ref.set({"messages": messages}, merge=True)

def search_recipe(query, k=3):
    """Search FAISS for the closest recipe matches."""
    query_embedding = model.encode(query, convert_to_numpy=True).reshape(1, -1)

    # Search FAISS for the closest match
    distances, indices = index.search(query_embedding, k)

    # Retrieve top-k matching recipes
    results = df.iloc[indices[0]]

    return results

# Example FAISS Search
query = "chicken, garlic, onion"
best_recipes = search_recipe(query)
print("FAISS Retrieval Successful!")

def chat_with_model(user_id, user_input):
    """Retrieve the latest user preferences from Firestore and generate a GPT response."""

    # 🔍 Always fetch the latest preference from Firestore before responding
    user_data = get_user_data(user_id)
    preferences = user_data.get("preferences", "No preference set") if user_data else "No preference set"

    print(f"✅ Retrieved latest preference for {user_id}: {preferences}")

    # If no preferences are set, ask the user
    if preferences == "No preference set":
        return "Please enter your dietary preferences (e.g., vegetarian, no beef, low-carb)."

    # 🔥 Retrieve recipes using FAISS based on user query
    best_recipes = search_recipe(user_input, k=3)

    # 📝 Format recipes for GPT input (Bullet points for ingredients, Numbered for instructions)
    formatted_recipes = "\n\n".join([
        f"**🍽 Title:** {row['title']}\n"
        f"**🛒 Ingredients:**\n"
        + "\n".join([f"- {ingredient}" for ingredient in row['ingredients'].split(", ")]) + "\n\n"
        f"**👨‍🍳 Instructions:**\n"
        + "\n".join([f"{i+1}. {step}" for i, step in enumerate(row['directions'].split(". "))])
        for _, row in best_recipes.iterrows()
    ])

    # 🎯 Strict System Prompt (Prevents GPT from using past conversation memory)
    system_prompt = f"""
    You are a professional chef assistant. The user follows these dietary preferences: {preferences}.

    Here are recommended recipes based on their preferences:
    {formatted_recipes}

    You must strictly follow the dietary preferences given. If the user contradicts a past statement,
    always prioritize their most recent preference retrieved from Firestore.
    """

    # 📝 Always start fresh conversation history to avoid past memory issues
    conversation = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_input}
    ]

    # 🚀 Generate response using GPT
    client = openai.OpenAI(api_key=openai_api_key)

    response = client.chat.completions.create(
        model="gpt-3.5-turbo",
        messages=conversation,
        max_tokens=300
    )

    reply = response.choices[0].message.content

    # 🔄 Save updated conversation for future use
    save_user_conversation(user_id, conversation)

    return reply

import asyncio
from telegram.ext import Application, CommandHandler, MessageHandler, filters, CallbackContext
from telegram import Update


async def start(update, context):
    user_id = update.message.chat_id
    await update.message.reply_text("🍽️ Welcome to appetAIse! Send me ingredients or a request, and I'll recommend recipes! Please let me know if you have any dietary preferences. Use /setpreference to reset preferences")


async def handle_message(update: Update, context: CallbackContext) -> None:
    """Handles user messages, ensures the latest preferences are retrieved."""
    user_id = str(update.message.chat_id)
    user_text = update.message.text.lower().strip()

    print(f"📩 Received message from {user_id}: {user_text}")  # ✅ Debugging

    # 🔍 Always retrieve the latest preference from Firestore
    user_ref = db.collection("users").document(user_id)
    user_doc = user_ref.get()

    if not user_doc.exists():
        await update.message.reply_text("⚠️ No dietary preference found. Please set one using `/setpreference`.")
        return

    user_data = user_doc.to_dict()
    preferences = user_data.get("preferences", "").lower()

    print(f"✅ Retrieved latest preference for {user_id}: {preferences}")

    # 🔥 Ensure GPT does not override preferences
    bot_reply = chat_with_model(user_id, user_text, preferences)

    print(f"🤖 Bot Reply: {bot_reply}")  # ✅ Debugging
    await update.message.reply_text(bot_reply)


async def handle_message(update: Update, context: CallbackContext) -> None:
    """Handles user messages, saves preferences, and recommends recipes."""
    user_id = str(update.message.chat_id)  # Convert to string for Firestore
    user_text = update.message.text.lower().strip()  # Convert text to lowercase for consistency

    print(f"📩 Received message from {user_id}: {user_text}")  # ✅ Debugging

    # 🔍 Check if user exists in Firestore
    user_ref = db.collection("users").document(user_id)
    user_doc = user_ref.get()

    if not user_doc.exists:
        print(f"⚠️ No data found for user {user_id}, saving preference...")
        user_ref.set({"preferences": user_text})  # Save user preference
        bot_reply = f"✅ Got it! Your dietary preference is now set as: {user_text}.\nNow you can ask me for recipe recommendations!"
    else:
        # 🔍 User exists, retrieve stored preference
        user_data = user_doc.to_dict()
        preferences = user_data.get("preferences", None)

        if preferences is None:
            print(f"⚠️ User {user_id} has no saved preferences, updating now...")
            user_ref.update({"preferences": user_text})  # Update user preference
            bot_reply = f"✅ Got it! Your dietary preference is now set as: {user_text}.\nNow you can ask me for recipe recommendations!"
        else:
            print(f"✅ User {user_id} has preference: {preferences}")

            # 🔥 Now recommend a recipe based on stored preference
            bot_reply = chat_with_model(user_id, user_text)

    print(f"🤖 Bot Reply: {bot_reply}")  # ✅ Debugging: Print bot's response before sending

    await update.message.reply_text(bot_reply)

def main():
    """Runs the Telegram bot with preference update support."""
    if not telegram_token:
        raise ValueError("❌ TELEGRAM_BOT_TOKEN is missing! Check your .env file.")

    print("✅ TELEGRAM_BOT_TOKEN Loaded Successfully!")

    app = Application.builder().token(telegram_token).build()

    # ✅ Add handlers
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("setpreference", set_preference))  # 🔥 New command for updating preferences
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    print("🤖 Bot is running!")

    if not asyncio.get_event_loop().is_running():
        asyncio.run(app.run_polling())
    else:
        loop = asyncio.get_event_loop()
        loop.create_task(app.run_polling())

main()

