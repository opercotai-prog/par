import os
from supabase import create_client

supabase = create_client(os.getenv("SUPABASE_URL"), os.getenv("SUPABASE_KEY"))

WHITE_LIST = ["тюмень", "тмн", "72", "республики", "широтная", "новопатрушево"]
BLACK_LIST = ["москва", "питер", "сочи", "крипта", "работа", "вакансии"]

def validate():
    res = supabase.table("channels").select("*").filter("stage", "eq", "new").execute()
    
    for row in res.data:
        text = (row['title'] or "") + " " + (row['description'] or "")
        text = text.lower()
        
        is_tyumen = any(word in text for word in WHITE_LIST)
        is_trash = any(word in text for word in BLACK_LIST)
        
        if is_tyumen and not is_trash:
            new_stage = "active"
        else:
            new_stage = "ignored"
            
        supabase.table("channels").update({"stage": new_stage}).eq("id", row['id']).execute()

if __name__ == "__main__":
    validate()
