from werkzeug.security import generate_password_hash

from database import get_db_connection, create_tables


create_tables()


connection = get_db_connection()


name = "System Admin"
email = "admin@gmail.com"
password = "admin123"
phone = "9999999999"
role = "admin"


hashed_password = generate_password_hash(password)


try:

    connection.execute("""
        INSERT INTO users
        (name, email, password, phone, role)

        VALUES (?, ?, ?, ?, ?)
    """,
    (
        name,
        email,
        hashed_password,
        phone,
        role
    ))

    connection.commit()

    print("Admin account created successfully.")

except Exception as error:

    print("Error:", error)

finally:

    connection.close()
