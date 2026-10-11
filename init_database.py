from app.database.database import Database
from app.violation.violation_logger import setup_database

db = Database()

db.create_tables()

db.close()

# The unified table used by red-light, speeding and the dashboard.
setup_database()

print("Database created successfully.")
