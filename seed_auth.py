import json
import os
from werkzeug.security import generate_password_hash
from app import app, db, User, Admin, Submission

def full_sync_auth():
    with app.app_context():
        print("--- STARTING FULL SYNC (JSON <-> DB) ---")

        # ==========================================
        # 1. SYNC ADMINS
        # ==========================================
        if os.path.exists('admins.json'):
            with open('admins.json', 'r') as f:
                admins_data = json.load(f)
            
            json_admin_names = set(admins_data.keys())
            db_admins = Admin.query.all()

            # A. DELETE Admins not in JSON
            for admin in db_admins:
                if admin.username not in json_admin_names:
                    print(f" [-] Deleting removed Admin: {admin.username}")
                    db.session.delete(admin)
            
            # B. ADD or UPDATE Admins from JSON
            for username, password in admins_data.items():
                existing = Admin.query.filter_by(username=username).first()
                hashed = generate_password_hash(password)
                if existing:
                    existing.password_hash = hashed
                    print(f" [~] Updated Admin: {username}")
                else:
                    new_admin = Admin(username=username, password_hash=hashed)
                    db.session.add(new_admin)
                    print(f" [+] Created Admin: {username}")

        # ==========================================
        # 2. SYNC PARTICIPANTS
        # ==========================================
        if os.path.exists('participants.json'):
            with open('participants.json', 'r') as f:
                users_data = json.load(f)

            json_user_names = set(users_data.keys())
            db_users = User.query.all()

            # A. DELETE Participants not in JSON
            for user in db_users:
                if user.username not in json_user_names:
                    print(f" [-] Deleting removed Participant: {user.username}")
                    # CRITICAL: Delete their submissions first to avoid DB errors
                    Submission.query.filter_by(user_id=user.id).delete()
                    db.session.delete(user)

            # B. ADD or UPDATE Participants from JSON
            for username, password in users_data.items():
                existing = User.query.filter_by(username=username).first()
                hashed = generate_password_hash(password)
                
                if existing:
                    # Update password, keep score/time intact
                    existing.password_hash = hashed
                    print(f" [~] Verified/Updated Participant: {username}")
                else:
                    # Create new
                    new_user = User(
                        username=username, 
                        password_hash=hashed, 
                        score=0, 
                        total_time=0.0, 
                        warnings=0
                    )
                    db.session.add(new_user)
                    print(f" [+] Created Participant: {username}")

        # ==========================================
        # 3. SAVE CHANGES
        # ==========================================
        try:
            db.session.commit()
            print("\n--- SUCCESS: Database is now exactly like your JSON files. ---")
        except Exception as e:
            db.session.rollback()
            print(f"\n--- ERROR: Sync failed: {e} ---")

if __name__ == "__main__":
    # Safety Prompt
    confirm = input("WARNING: This will DELETE users/admins not found in the JSON files.\nType 'yes' to proceed: ")
    if confirm.lower() == 'yes':
        full_sync_auth()
    else:
        print("Operation cancelled.")