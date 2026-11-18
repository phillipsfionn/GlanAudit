import os
from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from dotenv import load_dotenv
from sqlalchemy.sql import text

# Load the DATABASE_URL from your hidden .env file
load_dotenv()

# Initiait lize a basic Flask app
app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = os.getenv('DATABASE_URL')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)

def check_db():
    with app.app_context():
        try:
            # Attempt a simple query to verify the connection
            db.session.execute(text('SELECT 1'))
            print("\n------------------------------------------------")
            print("Connected to Supabase PostgreSQL!")
            print("------------------------------------------------\n")
        except Exception as e:
            print("\nCould not connect to Supabase.")
            print(f"Error details: {e}\n")

if __name__ == '__main__':
    check_db()