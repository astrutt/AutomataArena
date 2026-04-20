# ai_player/verify_save.py
import json
import os
import bot

def test_save():
    print(f"[*] Testing save_character with CHARACTER_FILE='{bot.CHARACTER_FILE}'")
    payload = {"token": "test_token", "bio": "Test Bio", "stats": {"cpu": 5}}
    
    # Trigger the save
    bot.save_character(payload)
    
    abs_expected = os.path.abspath(bot.CHARACTER_FILE)
    print(f"[*] Expected absolute path: {abs_expected}")
    
    if os.path.exists(bot.CHARACTER_FILE):
        print(f"[+] Success: {bot.CHARACTER_FILE} exists.")
        with open(bot.CHARACTER_FILE, 'r') as f:
            data = json.load(f)
            if data['token'] == 'test_token':
                print("[+] Success: Data matches expected payload.")
            else:
                print("[-] Error: Data mismatch.")
    else:
        print(f"[-] Error: {bot.CHARACTER_FILE} not found.")

if __name__ == "__main__":
    test_save()
