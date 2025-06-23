# apps/users/utils/normalizers.py

def normalize_email(email):
    if not isinstance(email, str):
        raise ValueError("El valor proporcionado como email no es válido.")
    return email.strip().lower()

def normalize_username(username):
    if not isinstance(username, str):
        raise ValueError("El valor proporcionado como username no es válido.")
    return username.strip().lower()
