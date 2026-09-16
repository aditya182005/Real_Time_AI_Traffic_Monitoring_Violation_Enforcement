from app.database.database import Database

db = Database()

db.create_tables()

db.close()

print("Database created successfully.")