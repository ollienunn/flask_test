# Webstore — Flask project

Simple teaching/demo webstore built with Flask. Features:
- Product catalogue, cart and checkout
- Admin interface to manage products and orders
- Order encryption (Fernet) for sensitive government fields
- Session timeout and admin controls
- Small easter-eggs (snake game, About-page secret)

## Prerequisites
- Python 3.10+ recommended (3.11+ OK)
- pip

## Quick setup (Windows / PowerShell)
1. Clone or open the project folder:
   cd "c:\Users\Oliver\OneDrive\Desktop\Year 11\SE\flask_test"

2. Create & activate venv:
   python -m venv .venv
   .\.venv\Scripts\Activate

3. Install requirements:
   pip install -r requirements.txt

4. Generate encryption key (one-time) and set env var (PowerShell example):
   python - <<'PY'
   from cryptography.fernet import Fernet
   print(Fernet.generate_key().decode())
   PY
   # copy printed key then:
   $env:DATA_ENC_KEY="PASTE_KEY_HERE"
   # for permanent (restart required):
   setx DATA_ENC_KEY "PASTE_KEY_HERE"

5. Optional environment variables (set as needed):
   - FLASK_SECRET             (defaults to "CheeseSauce")
   - DATA_ENC_KEY             (required for encrypt/decrypt of order fields)
   - ADMIN_USER is the user name for admins and is "Admin"
   - ADMIN_PASS is the password for the admin and is "MachZero" 
   - TEACHER_EGG_CODE, ABOUT_EGG_CODE (easter-egg codes)
   - SESSION_TIMEOUT_MINUTES (default 10)
   - SESSION_MAX_AGE_MINUTES (default 1440)

6. Run the app (in same shell where env vars are set):
   python app.py
   Open http://localhost:5000

## Files of interest
- app.py — main application
- templates/ — HTML templates (checkout.html, admin_order_detail.html, about.html, snake.html, ...)
- static/ — CSS, JS, images
- setup.db
- store.db — SQLite database (created/used by app)
- private_uploads/ — uploaded documents stored privately

## Database & backups
- Backup before migrations:
  copy .\store.db .\store.db.bak
- If you change DATA_ENC_KEY, existing encrypted data cannot be decrypted.
- If rows were inserted while DATA_ENC_KEY was missing, they may be NULL and are unrecoverable unless you have a DB backup.

## Migration script (encrypt existing plaintext rows)
If you need to encrypt plaintext values already in the DB, prepare DATA_ENC_KEY and run a migration script. (See earlier project notes / scripts or request the script.)

## Development helpers
- /admin/debug — shows whether DATA_ENC_KEY / Fernet works (admin-only)
- /debug/session — shows current session (only when app.debug or from localhost)
- /about/egg — unlocks About-page easter-egg for the current session
- /easter-egg?code=<code> — teacher easter-egg (sets session flag)
- /snake — plays the secret Snake game (session must have found_easter_egg)

## Installing required Python packages
Recommended install (after activating venv):
- pip install Flask python-dotenv cryptography

Or install all at once:
- pip install -r requirements.txt

## Requirements file
See `requirements.txt` for the exact pip packages used.

## Security notes
- Keep DATA_ENC_KEY and FLASK_SECRET private (do not commit to git).
- Limit admin credentials and never expose secrets to clients.
- Use HTTPS in production.

## License
Use as class/learning material. No warranty provided.
