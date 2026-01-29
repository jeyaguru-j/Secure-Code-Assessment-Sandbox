from app import app, db

with app.app_context():
    print("Creating database tables...")
    db.create_all()
    print("Done! Database is ready.")