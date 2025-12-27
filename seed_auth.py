import json
import os
from werkzeug.security import generate_password_hash
from app import app, db, User, Admin  # We will import models from app.py

def seed_data():
    with app.app_context():
        # 1. Create Tables if they don't exist (includes new Admin table)
        db.create_all()

        # --- SEED ADMINS ---
        if os.path.exists('admins.json'):
            with open('admins.json', 'r') as f:
                admins = json.load(f)
                print(f"Loading {len(admins)} admins...")
                
                for username, password in admins.items():
                    # Check if exists
                    if not Admin.query.filter_by(username=username).first():
                        hashed = generate_password_hash(password)
                        new_admin = Admin(username=username, password_hash=hashed)
                        db.session.add(new_admin)
        
        # --- SEED PARTICIPANTS ---
        if os.path.exists('participants.json'):
            with open('participants.json', 'r') as f:
                users = json.load(f)
                print(f"Loading {len(users)} participants...")
                
                for username, password in users.items():
                    # Check if exists
                    user = User.query.filter_by(username=username).first()
                    hashed = generate_password_hash(password)
                    if not user:
                        # Create new user with 0 score
                        new_user = User(username=username, password_hash=hashed, score=0)
                        db.session.add(new_user)
                    else:
                        # Update password if user exists (resetting db)
                        user.password_hash = hashed

        db.session.commit()
        print("Database seeding complete!")

if __name__ == "__main__":
    seed_data()