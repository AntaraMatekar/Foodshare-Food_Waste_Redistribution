from datetime import datetime
from flask import Flask, render_template, request, redirect, url_for, flash
from flask_login import (
    LoginManager, UserMixin, login_user, logout_user,
    login_required, current_user
)
from werkzeug.security import generate_password_hash, check_password_hash

from database import (
    get_db_connection, create_tables, update_expired_food,
    create_notification, mark_notification_read
)
from matching import calculate_match_score, get_match_label

app = Flask(__name__)
app.secret_key = "foodshare-secret-key"

login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = "login"


class User(UserMixin):
    def __init__(self, user_id, name, email, password, phone, role):
        self.id = user_id
        self.name = name
        self.email = email
        self.password = password
        self.phone = phone
        self.role = role


@login_manager.user_loader
def load_user(user_id):
    connection = get_db_connection()
    user = connection.execute(
        "SELECT * FROM users WHERE id = ?", (user_id,)
    ).fetchone()
    connection.close()

    if not user:
        return None

    return User(
        user["id"], user["name"], user["email"],
        user["password"], user["phone"], user["role"]
    )


@app.context_processor
def inject_notification_count():
    if current_user.is_authenticated:
        connection = get_db_connection()
        count = connection.execute("""
            SELECT COUNT(*) AS count
            FROM notifications
            WHERE user_id = ? AND is_read = 0
        """, (current_user.id,)).fetchone()["count"]
        connection.close()
        return {"unread_notifications": count}
    return {"unread_notifications": 0}


@app.route("/")
def home():
    return render_template("index.html")


@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        phone = request.form.get("phone", "").strip()
        role = request.form.get("role", "").strip().lower()

        if not name or not email or not password or role not in ("donor", "receiver"):
            flash("Please complete all required fields.")
            return render_template("register.html")

        connection = get_db_connection()
        try:
            connection.execute("""
                INSERT INTO users (name, email, password, phone, role)
                VALUES (?, ?, ?, ?, ?)
            """, (
                name, email, generate_password_hash(password), phone, role
            ))
            connection.commit()
            flash("Registration successful! Please login.")
            return redirect(url_for("login"))
        except Exception:
            flash("Email already registered.")
        finally:
            connection.close()

    return render_template("register.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")

        connection = get_db_connection()
        user = connection.execute(
            "SELECT * FROM users WHERE email = ?", (email,)
        ).fetchone()
        connection.close()

        if user and check_password_hash(user["password"], password):
            login_user(User(
                user["id"], user["name"], user["email"],
                user["password"], user["phone"], user["role"]
            ))

            if user["role"] == "donor":
                return redirect(url_for("donor_dashboard"))
            if user["role"] == "receiver":
                return redirect(url_for("receiver_dashboard"))
            return redirect(url_for("admin_dashboard"))

        flash("Invalid email or password.")

    return render_template("login.html")


@app.route("/logout")
@login_required
def logout():
    logout_user()
    flash("You have been logged out.")
    return redirect(url_for("home"))


@app.route("/donor/dashboard")
@login_required
def donor_dashboard():
    if current_user.role != "donor":
        flash("Access denied.")
        return redirect(url_for("home"))

    update_expired_food()
    connection = get_db_connection()

    donations = connection.execute("""
        SELECT *
        FROM food_donations
        WHERE donor_id = ?
        ORDER BY created_at DESC
    """, (current_user.id,)).fetchall()

    stats = connection.execute("""
        SELECT
            COUNT(*) AS total,
            SUM(CASE WHEN status = 'Available' THEN 1 ELSE 0 END) AS available,
            SUM(CASE WHEN status = 'Completed' THEN 1 ELSE 0 END) AS completed,
            SUM(CASE WHEN status = 'Expired' THEN 1 ELSE 0 END) AS expired
        FROM food_donations
        WHERE donor_id = ?
    """, (current_user.id,)).fetchone()

    pending = connection.execute("""
        SELECT COUNT(*) AS count
        FROM food_requests r
        JOIN food_donations f ON r.food_id = f.id
        WHERE f.donor_id = ? AND r.request_status = 'Pending'
    """, (current_user.id,)).fetchone()["count"]

    connection.close()

    return render_template(
        "donor_dashboard.html",
        donations=donations,
        stats=stats,
        pending_requests=pending
    )


@app.route("/donor/add-food", methods=["GET", "POST"])
@login_required
def add_food():
    if current_user.role != "donor":
        flash("Access denied.")
        return redirect(url_for("home"))

    if request.method == "POST":
        food_name = request.form.get("food_name", "").strip()
        category = request.form.get("category", "").strip()
        description = request.form.get("description", "").strip()
        prepared_time = request.form.get("prepared_time", "").strip()
        available_until = request.form.get("available_until", "").strip()
        location = request.form.get("location", "").strip()

        try:
            quantity = int(request.form.get("quantity", "0"))
        except ValueError:
            quantity = 0

        if not food_name or not category or quantity <= 0 or not available_until or not location:
            flash("Please enter valid food details.")
            return render_template("add_food.html")

        try:
            expiry = datetime.strptime(available_until, "%Y-%m-%dT%H:%M")
            if expiry <= datetime.now():
                flash("Available Until must be a future date and time.")
                return render_template("add_food.html")
        except ValueError:
            flash("Invalid expiry date/time.")
            return render_template("add_food.html")

        connection = get_db_connection()
        connection.execute("""
            INSERT INTO food_donations
            (donor_id, food_name, category, quantity, description,
             prepared_time, available_until, location, status, expiry_status)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'Available', 'Fresh')
        """, (
            current_user.id, food_name, category, quantity, description,
            prepared_time, available_until, location
        ))
        connection.commit()
        connection.close()

        flash("Food donation added successfully!")
        return redirect(url_for("donor_dashboard"))

    return render_template("add_food.html")


@app.route("/receiver/dashboard")
@login_required
def receiver_dashboard():
    if current_user.role != "receiver":
        flash("Access denied.")
        return redirect(url_for("home"))

    update_expired_food()

    search = request.args.get("search", "").strip()
    category = request.args.get("category", "").strip()
    receiver_location = request.args.get("location", "").strip()

    try:
        requested_quantity = max(1, int(request.args.get("quantity", "1")))
    except ValueError:
        requested_quantity = 1

    connection = get_db_connection()

    query = """
        SELECT *
        FROM food_donations
        WHERE status = 'Available'
          AND quantity > 0
    """
    parameters = []

    if search:
        query += " AND (food_name LIKE ? OR location LIKE ?)"
        value = f"%{search}%"
        parameters.extend([value, value])

    if category:
        query += " AND category = ?"
        parameters.append(category)

    query += " ORDER BY created_at DESC"

    foods = connection.execute(query, parameters).fetchall()
    connection.close()

    matched_foods = []
    for food in foods:
        result = calculate_match_score(
            food, receiver_location, category, requested_quantity
        )
        matched_foods.append({
            "food": food,
            "score": result["score"],
            "label": get_match_label(result["score"]),
            "reasons": result["reasons"]
        })

    matched_foods.sort(key=lambda item: item["score"], reverse=True)

    return render_template(
        "receiver_dashboard.html",
        matched_foods=matched_foods,
        search=search,
        category=category,
        location=receiver_location,
        quantity=requested_quantity
    )


@app.route("/receiver/request/<int:food_id>", methods=["GET", "POST"])
@login_required
def request_food(food_id):
    if current_user.role != "receiver":
        flash("Access denied.")
        return redirect(url_for("home"))

    update_expired_food()
    connection = get_db_connection()

    food = connection.execute("""
        SELECT *
        FROM food_donations
        WHERE id = ? AND status = 'Available' AND quantity > 0
    """, (food_id,)).fetchone()

    if not food:
        connection.close()
        flash("Food donation is no longer available or has expired.")
        return redirect(url_for("receiver_dashboard"))

    if request.method == "POST":
        try:
            quantity = int(request.form.get("quantity", "0"))
        except ValueError:
            quantity = 0

        if quantity <= 0 or quantity > food["quantity"]:
            flash("Please enter a valid quantity.")
            connection.close()
            return redirect(url_for("request_food", food_id=food_id))

        existing = connection.execute("""
            SELECT id
            FROM food_requests
            WHERE food_id = ? AND receiver_id = ?
              AND request_status IN ('Pending', 'Approved', 'Pickup Scheduled')
        """, (food_id, current_user.id)).fetchone()

        if existing:
            flash("You already have an active request for this food.")
            connection.close()
            return redirect(url_for("receiver_requests"))

        connection.execute("""
            INSERT INTO food_requests
            (food_id, receiver_id, quantity_requested, request_status)
            VALUES (?, ?, ?, 'Pending')
        """, (food_id, current_user.id, quantity))

        donor_id = food["donor_id"]
        connection.commit()
        connection.close()

        create_notification(
            donor_id,
            f"{current_user.name} requested {quantity} portion(s) of {food['food_name']}.",
            "Request"
        )

        flash("Food request submitted successfully!")
        return redirect(url_for("receiver_requests"))

    connection.close()
    return render_template("request_food.html", food=food)


@app.route("/donor/requests")
@login_required
def donor_requests():
    if current_user.role != "donor":
        flash("Access denied.")
        return redirect(url_for("home"))

    update_expired_food()
    connection = get_db_connection()
    requests_data = connection.execute("""
        SELECT r.*, f.food_name, f.location, f.available_until,
               f.quantity AS remaining_quantity,
               u.name AS receiver_name, u.phone AS receiver_phone
        FROM food_requests r
        JOIN food_donations f ON r.food_id = f.id
        JOIN users u ON r.receiver_id = u.id
        WHERE f.donor_id = ?
        ORDER BY r.request_date DESC
    """, (current_user.id,)).fetchall()
    connection.close()

    return render_template("donor_requests.html", requests=requests_data)


@app.route("/donor/request/<int:request_id>/approve", methods=["POST"])
@login_required
def approve_request(request_id):
    if current_user.role != "donor":
        flash("Access denied.")
        return redirect(url_for("home"))

    update_expired_food()
    connection = get_db_connection()

    data = connection.execute("""
        SELECT r.*, f.food_name, f.quantity, f.donor_id, f.status,
               f.available_until
        FROM food_requests r
        JOIN food_donations f ON r.food_id = f.id
        WHERE r.id = ?
    """, (request_id,)).fetchone()

    if not data or data["donor_id"] != current_user.id:
        connection.close()
        flash("Request not found or not authorized.")
        return redirect(url_for("donor_requests"))

    if data["request_status"] != "Pending":
        connection.close()
        flash("This request has already been processed.")
        return redirect(url_for("donor_requests"))

    if data["status"] != "Available" or data["quantity_requested"] > data["quantity"]:
        connection.close()
        flash("This food is no longer available in the requested quantity.")
        return redirect(url_for("donor_requests"))

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    remaining = data["quantity"] - data["quantity_requested"]

    # Reserve the requested quantity.
    connection.execute("""
        UPDATE food_requests
        SET request_status = 'Approved',
            approved_at = ?,
            updated_at = ?
        WHERE id = ?
    """, (now, now, request_id))

    new_status = "Available" if remaining > 0 else "Pickup Scheduled"

    connection.execute("""
        UPDATE food_donations
        SET quantity = ?, status = ?, updated_at = ?
        WHERE id = ?
    """, (remaining, new_status, now, data["food_id"]))

    connection.commit()
    receiver_id = data["receiver_id"]
    connection.close()

    create_notification(
        receiver_id,
        f"Your request for {data['food_name']} was approved. Contact the donor to arrange pickup.",
        "Approval"
    )

    flash("Request approved. The receiver can now arrange pickup.")
    return redirect(url_for("donor_requests"))


@app.route("/donor/request/<int:request_id>/reject", methods=["POST"])
@login_required
def reject_request(request_id):
    if current_user.role != "donor":
        flash("Access denied.")
        return redirect(url_for("home"))

    connection = get_db_connection()
    data = connection.execute("""
        SELECT r.*, f.food_name, f.donor_id
        FROM food_requests r
        JOIN food_donations f ON r.food_id = f.id
        WHERE r.id = ?
    """, (request_id,)).fetchone()

    if not data or data["donor_id"] != current_user.id:
        connection.close()
        flash("Request not found or not authorized.")
        return redirect(url_for("donor_requests"))

    if data["request_status"] != "Pending":
        connection.close()
        flash("This request has already been processed.")
        return redirect(url_for("donor_requests"))

    connection.execute("""
        UPDATE food_requests
        SET request_status = 'Rejected',
            updated_at = ?
        WHERE id = ?
    """, (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), request_id))
    connection.commit()
    receiver_id = data["receiver_id"]
    connection.close()

    create_notification(
        receiver_id,
        f"Your request for {data['food_name']} was rejected.",
        "Rejection"
    )

    flash("Food request rejected.")
    return redirect(url_for("donor_requests"))


@app.route("/donor/request/<int:request_id>/schedule", methods=["POST"])
@login_required
def schedule_pickup(request_id):
    if current_user.role != "donor":
        flash("Access denied.")
        return redirect(url_for("home"))

    pickup_time = request.form.get("pickup_time", "").strip()
    if not pickup_time:
        flash("Please select a pickup time.")
        return redirect(url_for("donor_requests"))

    connection = get_db_connection()
    data = connection.execute("""
        SELECT r.*, f.food_name, f.donor_id
        FROM food_requests r
        JOIN food_donations f ON r.food_id = f.id
        WHERE r.id = ?
    """, (request_id,)).fetchone()

    if not data or data["donor_id"] != current_user.id:
        connection.close()
        flash("Request not found or not authorized.")
        return redirect(url_for("donor_requests"))

    if data["request_status"] != "Approved":
        connection.close()
        flash("Only approved requests can be scheduled.")
        return redirect(url_for("donor_requests"))

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    connection.execute("""
        UPDATE food_requests
        SET request_status = 'Pickup Scheduled',
            pickup_time = ?,
            updated_at = ?
        WHERE id = ?
    """, (pickup_time, now, request_id))
    connection.commit()
    receiver_id = data["receiver_id"]
    connection.close()

    create_notification(
        receiver_id,
        f"Pickup scheduled for {data['food_name']} at {pickup_time}.",
        "Pickup"
    )

    flash("Pickup scheduled successfully.")
    return redirect(url_for("donor_requests"))


@app.route("/donor/request/<int:request_id>/complete", methods=["POST"])
@login_required
def complete_request(request_id):
    if current_user.role != "donor":
        flash("Access denied.")
        return redirect(url_for("home"))

    connection = get_db_connection()
    data = connection.execute("""
        SELECT r.*, f.food_name, f.donor_id, f.quantity
        FROM food_requests r
        JOIN food_donations f ON r.food_id = f.id
        WHERE r.id = ?
    """, (request_id,)).fetchone()

    if not data or data["donor_id"] != current_user.id:
        connection.close()
        flash("Request not found or not authorized.")
        return redirect(url_for("donor_requests"))

    if data["request_status"] not in ("Approved", "Pickup Scheduled"):
        connection.close()
        flash("Only approved or scheduled requests can be completed.")
        return redirect(url_for("donor_requests"))

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    connection.execute("""
        UPDATE food_requests
        SET request_status = 'Completed',
            completed_at = ?,
            updated_at = ?
        WHERE id = ?
    """, (now, now, request_id))

    # If no remaining quantity exists, close the donation.
    if data["quantity"] <= 0:
        connection.execute("""
            UPDATE food_donations
            SET status = 'Completed',
                expiry_status = 'Completed',
                completed_at = ?,
                updated_at = ?
            WHERE id = ?
        """, (now, now, data["food_id"]))

    connection.commit()
    receiver_id = data["receiver_id"]
    connection.close()

    create_notification(
        receiver_id,
        f"Your {data['food_name']} redistribution has been completed.",
        "Completion"
    )

    flash("Donation/request marked as completed.")
    return redirect(url_for("donor_requests"))


@app.route("/receiver/requests")
@login_required
def receiver_requests():
    if current_user.role != "receiver":
        flash("Access denied.")
        return redirect(url_for("home"))

    connection = get_db_connection()
    requests_data = connection.execute("""
        SELECT r.*, f.food_name, f.location, f.available_until,
               u.name AS donor_name, u.phone AS donor_phone
        FROM food_requests r
        JOIN food_donations f ON r.food_id = f.id
        JOIN users u ON f.donor_id = u.id
        WHERE r.receiver_id = ?
        ORDER BY r.request_date DESC
    """, (current_user.id,)).fetchall()
    connection.close()

    return render_template("receiver_requests.html", requests=requests_data)


@app.route("/receiver/request/<int:request_id>/cancel", methods=["POST"])
@login_required
def cancel_request(request_id):
    if current_user.role != "receiver":
        flash("Access denied.")
        return redirect(url_for("home"))

    connection = get_db_connection()
    data = connection.execute("""
        SELECT r.*, f.food_name, f.quantity, f.status
        FROM food_requests r
        JOIN food_donations f ON r.food_id = f.id
        WHERE r.id = ? AND r.receiver_id = ?
    """, (request_id, current_user.id)).fetchone()

    if not data:
        connection.close()
        flash("Request not found.")
        return redirect(url_for("receiver_requests"))

    if data["request_status"] != "Pending":
        connection.close()
        flash("Only pending requests can be cancelled.")
        return redirect(url_for("receiver_requests"))

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    connection.execute("""
        UPDATE food_requests
        SET request_status = 'Cancelled', updated_at = ?
        WHERE id = ?
    """, (now, request_id))
    connection.commit()
    connection.close()

    flash("Request cancelled.")
    return redirect(url_for("receiver_requests"))


@app.route("/notifications")
@login_required
def notifications():
    connection = get_db_connection()
    items = connection.execute("""
        SELECT *
        FROM notifications
        WHERE user_id = ?
        ORDER BY created_at DESC
    """, (current_user.id,)).fetchall()
    connection.close()
    return render_template("notifications.html", notifications=items)


@app.route("/notifications/<int:notification_id>/read", methods=["POST"])
@login_required
def notification_read(notification_id):
    mark_notification_read(notification_id, current_user.id)
    return redirect(url_for("notifications"))


@app.route("/admin/dashboard")
@login_required
def admin_dashboard():
    if current_user.role != "admin":
        flash("Access denied.")
        return redirect(url_for("home"))

    update_expired_food()
    connection = get_db_connection()

    users = connection.execute("""
        SELECT * FROM users ORDER BY id DESC
    """).fetchall()

    foods = connection.execute("""
        SELECT f.*, u.name AS donor_name
        FROM food_donations f
        JOIN users u ON f.donor_id = u.id
        ORDER BY f.created_at DESC
    """).fetchall()

    requests_data = connection.execute("""
        SELECT r.*, f.food_name, u.name AS receiver_name
        FROM food_requests r
        JOIN food_donations f ON r.food_id = f.id
        JOIN users u ON r.receiver_id = u.id
        ORDER BY r.request_date DESC
    """).fetchall()

    impact = connection.execute("""
        SELECT
            COUNT(*) AS donations,
            COALESCE(SUM(CASE WHEN status = 'Completed' THEN 1 ELSE 0 END), 0) AS completed,
            COALESCE(SUM(CASE WHEN status = 'Expired' THEN 1 ELSE 0 END), 0) AS expired,
            COALESCE(SUM(CASE WHEN status IN ('Available', 'Pickup Scheduled') THEN quantity ELSE 0 END), 0) AS available_portions,
            COALESCE(SUM(CASE WHEN status = 'Completed' THEN quantity ELSE 0 END), 0) AS completed_quantity
        FROM food_donations
    """).fetchone()

    connection.close()

    return render_template(
        "admin_dashboard.html",
        users=users,
        foods=foods,
        requests=requests_data,
        impact=impact
    )


create_tables()
update_expired_food()


if __name__ == "__main__":
    app.run(debug=True)
