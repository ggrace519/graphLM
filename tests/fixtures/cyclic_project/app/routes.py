from app.services import process_data

def register_routes():
    data = process_data()
    print(f"Registered routes with {len(data)} items")
