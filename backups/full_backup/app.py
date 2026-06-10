from flask import Flask, render_template, request, redirect, session, make_response
from sqlalchemy import create_engine
import pandas as pd
from sqlalchemy import create_engine
import os
import sqlite3
import os
import shutil
from datetime import datetime
from zoneinfo import ZoneInfo
from io import BytesIO
from reportlab.graphics.shapes import Drawing, Rect

from reportlab.lib.pagesizes import legal, landscape
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, Image
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_LEFT, TA_CENTER
import json
import os

USERS_FILE = "users.json"

def load_users():

    if not os.path.exists(USERS_FILE):
        return {}

    with open(USERS_FILE, "r") as f:
        return json.load(f)

def save_users(users):

    with open(USERS_FILE, "w") as f:
        json.dump(users, f, indent=4)


app = Flask(__name__)
app.secret_key = "aado_secret_key_2026"

DATABASE_FILE = "database.db"

DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql+psycopg2://aado_admin:Aado123!@localhost:5432/aado_db"
)

engine = create_engine(DATABASE_URL)

def init_users_table():

    with engine.begin() as conn:
        conn.exec_driver_sql("""
            CREATE TABLE IF NOT EXISTS users (
                id SERIAL PRIMARY KEY,
                username TEXT UNIQUE NOT NULL,
                password TEXT NOT NULL,
                role TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending'
            )
        """)

    with engine.begin() as conn:
        conn.exec_driver_sql(
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS fullname TEXT"
        )

    with engine.begin() as conn:
        conn.exec_driver_sql(
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS position TEXT"
        )

    with engine.begin() as conn:
        conn.exec_driver_sql(
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS student_id TEXT"
        )

    with engine.begin() as conn:
        result = conn.exec_driver_sql(
            "SELECT COUNT(*) FROM users WHERE role = %s",
            ("super_admin",)
        ).scalar()

        if result == 0:
            conn.exec_driver_sql(
                """
                INSERT INTO users
                (username, password, fullname, position, role, status)
                VALUES
                (%s, %s, %s, %s, %s, %s)
                """,
                (
                    "superadmin",
                    "superadmin123",
                    "Super Admin",
                    "System Administrator",
                    "super_admin",
                    "approved"
                )
            )


def init_sports_table():

    with engine.begin() as conn:
        conn.exec_driver_sql("""
            CREATE TABLE IF NOT EXISTS sports (
                id SERIAL PRIMARY KEY,
                sport_name TEXT NOT NULL,
                level_group TEXT NOT NULL
            )
        """)

        count = conn.exec_driver_sql(
            "SELECT COUNT(*) FROM sports"
        ).scalar()

        if count == 0:
            default_sports = [
                ("Badminton", "basic_ed"),
                ("Baseball - Boys", "basic_ed"),
                ("Basketball - Boys", "basic_ed"),
                ("Basketball - Girls", "basic_ed"),
                ("Chess", "basic_ed"),
                ("Lawn Tennis", "basic_ed"),
                ("PEP Squad", "basic_ed"),
                ("Taekwando", "basic_ed"),
                ("Volleyball - Boys", "basic_ed"),
                ("Volleyball - Girls", "basic_ed"),

                ("Basketball", "college"),
                ("Volleyball", "college"),
                ("Badminton", "college"),
                ("Chess", "college"),
                ("Taekwondo", "college")
            ]

            for sport_name, level_group in default_sports:
                conn.exec_driver_sql(
                    """
                    INSERT INTO sports (sport_name, level_group)
                    VALUES (%s, %s)
                    """,
                    (sport_name, level_group)
                )


def get_sports_by_group(level_group):
    with engine.begin() as conn:
        rows = conn.exec_driver_sql(
            """
            SELECT sport_name
            FROM sports
            WHERE level_group = %s
            ORDER BY sport_name
            """,
            (level_group,)
        ).fetchall()

    return [row[0] for row in rows]

def load_data():
    try:
        df = pd.read_sql_query(
            "SELECT * FROM grades",
            engine
        )

        # Compatibility fix:
        # Old SQLite used "Sports Events"; PostgreSQL table may use "Sport".
        # This makes both names available so old templates/routes will not crash.
        if "Sport" in df.columns and "Sports Events" not in df.columns:
            df["Sports Events"] = df["Sport"]

        if "Sports Events" in df.columns and "Sport" not in df.columns:
            df["Sport"] = df["Sports Events"]

        return df

    except Exception as e:
        print("LOAD DATA ERROR:", e)
        return pd.DataFrame()

def filter_data_by_role(df):
    role = session.get("role")

    if df.empty:
        return df

    grade_level = (
        df["Grade Level"].astype(str).str.strip()
        if "Grade Level" in df.columns
        else pd.Series([""] * len(df), index=df.index)
    )

    sports_events = (
        df["Sports Events"].astype(str).str.strip()
        if "Sports Events" in df.columns
        else pd.Series([""] * len(df), index=df.index)
    )

    college_sports = get_sports_by_group("college")

    college_mask = (
        grade_level.str.contains("College", case=False, na=False)
        |
        sports_events.isin(college_sports)
    )

    if role == "admin_college":
        return df[college_mask]

    if role == "admin_jhs_shs":
        return df[~college_mask]

    return df

def auto_backup_database():
    backup_folder = "backups"

    if not os.path.exists(backup_folder):
        os.makedirs(backup_folder)

    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    backup_name = f"database_backup_{timestamp}.db"
    backup_path = os.path.join(backup_folder, backup_name)

    if os.path.exists(DATABASE_FILE):
        shutil.copy(DATABASE_FILE, backup_path)


def save_data(df):

    auto_backup_database()

    df.to_sql(
        "grades",
        engine,
        if_exists="replace",
        index=False
    )


def show_value(val):
    if pd.isna(val):
        return ""
    if str(val).lower() == "nan":
        return ""
    return val


def normalize_term(term):
    term = str(term).strip().upper()

    if term in ["", "NAN", "NONE"]:
        return ""

    if term in ["1ST", "1ST TERM", "FIRST", "FIRST TERM", "TERM 1", "TERM1", "1"]:
        return "TERM 1"

    if term in ["2ND", "2ND TERM", "SECOND", "SECOND TERM", "TERM 2", "TERM2", "2"]:
        return "TERM 2"

    if term in ["3RD", "3RD TERM", "THIRD", "THIRD TERM", "TERM 3", "TERM3", "3"]:
        return "TERM 3"

    return term

def normalize_all_terms(df):
    if "Term" in df.columns:
        df["Term"] = df["Term"].astype(str).apply(normalize_term)
    return df


def get_subject(row):
    subject = row.get("Subject_Display")

    if pd.isna(subject) or str(subject).strip() == "" or str(subject).lower() == "nan":
        subject = row.get("Subject")

    if pd.isna(subject) or str(subject).strip() == "" or str(subject).lower() == "nan":
        subject = row.get("Subject Name")

    if pd.isna(subject) or str(subject).strip() == "" or str(subject).lower() == "nan":
        subject = row.get("Learning Area")

    if pd.isna(subject) or str(subject).lower() == "nan":
        subject = ""

    return str(subject)


def is_shs(grade_level):
    grade_level = str(grade_level)
    return "11" in grade_level or "12" in grade_level

def is_college(grade_level):
    grade_level = str(grade_level).lower()
    return "college" in grade_level


def number_or_blank(value):
    if pd.isna(value) or str(value).strip() == "" or str(value).lower() == "nan":
        return ""

    try:
        num = float(value)
        if num.is_integer():
            return str(int(num))
        return str(num)
    except:
        return str(value)


def compute_average(values):
    grades = []

    for value in values:
        try:
            if str(value).strip() != "" and str(value).lower() != "nan":
                grades.append(float(value))
        except:
            pass

    if not grades:
        return "", "NO GRADE"

    average = int((sum(grades) / len(grades)) + 0.5)
    remarks = "PASSED" if average >= 75 else "FAILED"

    return average, remarks


def compute_college_remarks(grade):
    grade = str(grade).strip().upper()

    if grade == "" or grade == "NAN":
        return ""

    if grade == "R":
        return "REPEAT"

    if grade in ["INC", "INCOMPLETE"]:
        return "INCOMPLETE"

    if grade in ["DR", "DROP", "DROPPED"]:
        return "DROPPED"

    if grade in ["0", "0.0", "0.00"]:
        return "FAILED"

    try:
        grade_num = float(grade)

        if 1.00 <= grade_num <= 4.00:
            return "PASSED"

    except:
        return ""

    return ""

def promote_grade_level(grade_level, year_level=""):
    grade_level = str(grade_level).strip()
    year_level = str(year_level).strip()

    grade_promotion = {
        "Grade 7": "Grade 8",
        "Grade 8": "Grade 9",
        "Grade 9": "Grade 10",
        "Grade 10": "Grade 11",
        "Grade 11": "Grade 12",
        "Grade 12": "Graduated"
    }

    college_promotion = {
        "1st Year": "2nd Year",
        "2nd Year": "3rd Year",
        "3rd Year": "4th Year",
        "4th Year": "Graduated"
    }

    if grade_level == "College":
        return "College", college_promotion.get(year_level, year_level)

    return grade_promotion.get(grade_level, grade_level), year_level


def get_student_level_code(grade_level):
    grade_level = str(grade_level)

    if "College" in grade_level:
        return "COL"

    if "11" in grade_level or "12" in grade_level:
        return "SHS"

    return "JHS"


def generate_case_no(grade_level):
    level_code = get_student_level_code(grade_level)
    year = datetime.now().year
    timestamp = datetime.now().strftime("%m%d%H%M%S")

    return f"AADO-{level_code}-{year}-{timestamp}"

@app.route("/login", methods=["GET", "POST"])
def login():
    error = ""

    if request.method == "POST":
        username = request.form.get("username")
        password = request.form.get("password")

        with engine.begin() as conn:
            user = conn.exec_driver_sql(
                """
                SELECT username, password, role, status, fullname, position, student_id
                FROM users
                WHERE username = %s
                """,
                (username,)
            ).fetchone()

        if user is None:
            error = "Invalid username or password"

        elif password != user[1]:
            error = "Invalid username or password"

        elif user[3] != "approved":
            error = "Your account is still pending approval"

        else:
            session["logged_in"] = True
            session["username"] = user[0]
            session["role"] = user[2]
            session["fullname"] = user[4]
            session["position"] = user[5]
            session["student_id"] = user[6]

            if user[2] == "student":
                return redirect("/student_dashboard")

            if user[2] == "assistant":
                return redirect("/student_list")

            return redirect("/")

    return render_template("login.html", error=error)


@app.route("/register", methods=["GET", "POST"])
def register():
    error = ""
    success = ""

    if request.method == "POST":

        username = request.form.get("username")
        password = request.form.get("password")
        fullname = request.form.get("fullname")
        position = request.form.get("position")
        role = request.form.get("role")
        student_id = request.form.get("student_id", "")

        if role not in ["super_admin", "admin_jhs_shs", "admin_college", "assistant", "student"]:
            error = "Invalid role selected"

        elif role == "student" and student_id.strip() == "":
            error = "Student ID is required for student athletes"

        else:
            try:
                with engine.begin() as conn:
                    conn.exec_driver_sql(
                        """
                        INSERT INTO users
                        (
                            username,
                            password,
                            fullname,
                            position,
                            role,
                            status,
                            student_id
                        )
                        VALUES
                        (
                            %s,
                            %s,
                            %s,
                            %s,
                            %s,
                            'pending',
                            %s
                        )
                        """,
                        (
                            username,
                            password,
                            fullname,
                            position,
                            role,
                            student_id
                        )
                    )

                success = "Account registered. Please wait for Super Admin approval."

            except Exception as e:
                print("REGISTER ERROR:", e)
                error = "Username already exists"

    return render_template(
        "register.html",
        error=error,
        success=success
    )


@app.route("/manage_accounts")
def manage_accounts():
    if session.get("role") != "super_admin":
        return redirect("/")

    with engine.begin() as conn:
        users = conn.exec_driver_sql("""
            SELECT id, username, role, status
            FROM users
            ORDER BY id DESC
        """).fetchall()

    return render_template(
        "manage_accounts.html",
        users=users
    )


@app.route("/approve_account/<int:user_id>")
def approve_account(user_id):
    if session.get("role") != "super_admin":
        return redirect("/")

    with engine.begin() as conn:
        conn.exec_driver_sql(
            "UPDATE users SET status = 'approved' WHERE id = %s",
            (user_id,)
        )

    return redirect("/manage_accounts")


@app.route("/reject_account/<int:user_id>")
def reject_account(user_id):
    if session.get("role") != "super_admin":
        return redirect("/")

    with engine.begin() as conn:
        conn.exec_driver_sql(
            "UPDATE users SET status = 'rejected' WHERE id = %s",
            (user_id,)
        )

    return redirect("/manage_accounts")


@app.route("/delete_account/<int:user_id>")
def delete_account(user_id):
    if session.get("role") != "super_admin":
        return redirect("/")

    current_username = session.get("username")

    with engine.begin() as conn:
        user = conn.exec_driver_sql(
            """
            SELECT username
            FROM users
            WHERE id = %s
            """,
            (user_id,)
        ).fetchone()

        if user and user[0] == current_username:
            return redirect("/manage_accounts")

        conn.exec_driver_sql(
            """
            DELETE FROM users
            WHERE id = %s
            """,
            (user_id,)
        )

    return redirect("/manage_accounts")


@app.route("/logout")
def logout():
    session.clear()
    return redirect("/login")


@app.before_request
def protect_pages():
    allowed_routes = ["login", "register", "static"]

    if request.endpoint in allowed_routes:
        return

    if not session.get("logged_in"):
        return redirect("/login")

    role = session.get("role")

    if role == "student":
        student_allowed_routes = [
            "student_dashboard",
            "edit_student_own_profile",
            "logout",
            "static"
        ]

        if request.endpoint not in student_allowed_routes:
            return redirect("/student_dashboard")

    if role == "assistant":
        assistant_allowed_routes = [
            "student_list",
            "add_student",
            "add_grade",
            "logout",
            "static"
        ]

        if request.endpoint not in assistant_allowed_routes:
            return redirect("/student_list")


@app.route("/")
def dashboard():

    df = load_data()
    df = filter_data_by_role(df)

    role = session.get("role")

    if df.empty:
        total_students = 0
        passed_students = 0
        failed_students = 0
        total_sports = 0

    else:

        total_students = df["Student ID"].astype(str).nunique()

        failed_student_ids = set()

        for _, row in df.iterrows():

            student_id = str(row.get("Student ID", "")).strip()
            grade_level = str(row.get("Grade Level", "")).strip()

            if student_id == "":
                continue

            # =========================
            # COLLEGE FAILED LOGIC
            # =========================
            if is_college(grade_level):

                grade = str(row.get("Final Term Grade", "")).strip().upper()

                if grade in [
                    "0",
                    "0.0",
                    "0.00",
                    "R",
                    "INC",
                    "INCOMPLETE",
                    "DR",
                    "DROP",
                    "DROPPED"
                ]:
                    failed_student_ids.add(student_id)

            # =========================
            # JHS / SHS FAILED LOGIC
            # =========================
            else:

                grade = row.get("Final Term Grade")

                try:
                    grade_num = float(grade)

                    if grade_num < 75:
                        failed_student_ids.add(student_id)

                except:
                    pass

        failed_students = len(failed_student_ids)

        passed_students = (
            total_students - failed_students
        )

        total_sports = (
            df["Sports Events"]
            .dropna()
            .astype(str)
            .nunique()
        )

    # =========================
    # DASHBOARD TITLE
    # =========================

    if role == "super_admin":
        dashboard_title = "Super Admin Dashboard"

    elif role == "admin_jhs_shs":
        dashboard_title = "JHS / SHS Dashboard"

    elif role == "admin_college":
        dashboard_title = "College Dashboard"

    else:
        dashboard_title = "AADO Dashboard"

    return render_template(
        "dashboard.html",

        dashboard_title=dashboard_title,

        total_students=total_students,
        passed_students=passed_students,
        failed_students=failed_students,
        total_sports=total_sports
    )


@app.route("/student_dashboard")
def student_dashboard():

    student_id = session.get("student_id")

    if not student_id:
        student_id = session.get("username")

    df = load_data()

    student_records = df[
        df["Student ID"].astype(str) == str(student_id)
    ]

    if student_records.empty:
        return render_template(
            "student_dashboard.html",
            student=None,
            grouped_grades={}
        )

    student = student_records.iloc[0].to_dict()
    grade_level = str(student.get("Grade Level", ""))

    if is_college(grade_level):
        student_level = "COLLEGE"
    elif is_shs(grade_level):
        student_level = "SHS"
    else:
        student_level = "JHS"

    grouped_grades = {}

    for _, row in student_records.iterrows():

        subject = get_subject(row)

        if subject.strip() == "":
            continue

        academic_year = str(show_value(row.get("Academic Year")))
        term = normalize_term(row.get("Term"))

        group_title = f"AY {academic_year} - {term}"

        if group_title not in grouped_grades:
            grouped_grades[group_title] = []

        grouped_grades[group_title].append({
            "subject": subject,
            "midterm": number_or_blank(row.get("Midterm")),
            "final": number_or_blank(row.get("Final")),
            "q1": number_or_blank(row.get("Q1")),
            "q2": number_or_blank(row.get("Q2")),
            "q3": number_or_blank(row.get("Q3")),
            "q4": number_or_blank(row.get("Q4")),
            "final_grade": number_or_blank(row.get("Final Term Grade")),
            "remarks": show_value(row.get("Remarks"))
        })

    return render_template(
        "student_dashboard.html",
        student=student,
        grouped_grades=grouped_grades,
        student_level=student_level
)

@app.route("/edit_student_own_profile", methods=["GET", "POST"])
def edit_student_own_profile():

    student_id = session.get("student_id")

    if not student_id:
        student_id = session.get("username")

    df = load_data()

    student_records = df[
        df["Student ID"].astype(str) == str(student_id)
    ]

    if student_records.empty:
        return "Student profile not found. Please contact AADO."

    student = student_records.iloc[0].to_dict()

    if request.method == "POST":

        contact_number = request.form.get("contact_number", "")
        email = request.form.get("email", "")

        mask = df["Student ID"].astype(str) == str(student_id)

        df.loc[mask, "Contact Number"] = contact_number
        df.loc[mask, "Email"] = email

        save_data(df)

        return redirect("/student_dashboard")

    return render_template(
        "edit_student_own_profile.html",
        student=student,
        show_value=show_value
    )

@app.route("/student_list")
def student_list():
    df = load_data()
    df = filter_data_by_role(df)

    if df.empty:
        return render_template(
            "student_list.html",
            students=pd.DataFrame(),
            sports=[],
            grade_levels=[],
            show_value=show_value
        )

    role = session.get("role")

    if role == "admin_college":
        sports = get_sports_by_group("college")
    elif role == "admin_jhs_shs":
        sports = get_sports_by_group("basic_ed")
    else:
        sports = (
            get_sports_by_group("basic_ed")
            + get_sports_by_group("college")
        )

    sports = sorted(list(set(sports)))

    grade_levels = sorted(
        df["Grade Level"]
        .dropna()
        .astype(str)
        .unique()
    )

    filtered_df = df.copy()

    sport_filter = request.args.get("sport", "")
    grade_filter = request.args.get("grade_level", "")
    search = request.args.get("search", "")

    if sport_filter:
        filtered_df = filtered_df[
            filtered_df["Sports Events"].astype(str) == sport_filter
        ]

    if grade_filter:
        filtered_df = filtered_df[
            filtered_df["Grade Level"].astype(str) == grade_filter
        ]

    if search:
        filtered_df = filtered_df[
            filtered_df["Full Name"].astype(str).str.contains(search, case=False, na=False)
            |
            filtered_df["Student ID"].astype(str).str.contains(search, case=False, na=False)
        ]

    students = (
        filtered_df
        .drop_duplicates(subset=["Student ID"])
        .sort_values(by="Full Name")
    )

    return render_template(
        "student_list.html",
        students=students,
        sports=sports,
        grade_levels=grade_levels,
        show_value=show_value
    )

@app.route("/add_grade/<student_id>", methods=["GET", "POST"])
def add_grade(student_id):
    df = load_data()

    student_data = df[
        df["Student ID"].astype(str) == str(student_id)
    ]

    if student_data.empty:
        return "Student not found"

    student = student_data.iloc[0].to_dict()
    grade_level = str(student.get("Grade Level", ""))

    if is_college(grade_level):
        student_level = "COLLEGE"
    elif is_shs(grade_level):
        student_level = "SHS"
    else:
        student_level = "JHS"

    if request.method == "POST":

        academic_year = request.form.get("academic_year", "")

        subjects = request.form.getlist("subject[]")
        subject_sections = request.form.getlist("subject_section[]")
        terms = request.form.getlist("term[]")

        q1s = request.form.getlist("q1[]")
        q2s = request.form.getlist("q2[]")
        q3s = request.form.getlist("q3[]")
        q4s = request.form.getlist("q4[]")

        midterms = request.form.getlist("midterm[]")
        finals = request.form.getlist("final[]")

        for i in range(len(subjects)):

            subject = subjects[i].strip()

            if subject == "":
                continue

            subject_section = subject_sections[i] if i < len(subject_sections) else ""
            term_value = terms[i] if i < len(terms) else ""

            if student_level == "COLLEGE":
                saved_term = term_value
            else:
                saved_term = normalize_term(term_value)

            row = {
                "Student ID": student.get("Student ID", ""),
                "Full Name": student.get("Full Name", ""),
                "Grade Level": student.get("Grade Level", ""),

                "Section": student.get("Section", ""),
                "Strand": student.get("Strand", ""),

                "Year Level": student.get("Year Level", ""),
                "Course / Program": student.get("Course / Program", ""),
                "College": student.get("College", ""),

                "Sports Events": student.get("Sports Events", student.get("Sport", "")),
                "Sport": student.get("Sport", student.get("Sports Events", "")),

                "Academic Year": academic_year,
                "Term": saved_term,

                "Subject_Display": subject,
                "Subject": subject,
                "Subject Section": subject_section
            }

            if student_level == "COLLEGE":

                midterm = midterms[i] if i < len(midterms) else ""
                final = finals[i] if i < len(finals) else ""

                row["Midterm"] = midterm
                row["Final"] = final

                row["Q1"] = ""
                row["Q2"] = ""
                row["Q3"] = ""
                row["Q4"] = ""

                # Final grade ang basehan ng final term grade at remarks
                row["Final Term Grade"] = final
                row["Remarks"] = compute_college_remarks(final)

            elif student_level == "SHS":

                midterm = midterms[i] if i < len(midterms) else ""
                final = finals[i] if i < len(finals) else ""

                row["Midterm"] = midterm
                row["Final"] = final

                row["Q1"] = ""
                row["Q2"] = ""
                row["Q3"] = ""
                row["Q4"] = ""

                avg, remarks = compute_average([midterm, final])

                row["Final Term Grade"] = avg
                row["Remarks"] = "" if remarks == "NO GRADE" else remarks

            else:

                q1 = q1s[i] if i < len(q1s) else ""
                q2 = q2s[i] if i < len(q2s) else ""
                q3 = q3s[i] if i < len(q3s) else ""
                q4 = q4s[i] if i < len(q4s) else ""

                row["Q1"] = q1
                row["Q2"] = q2
                row["Q3"] = q3
                row["Q4"] = q4

                row["Midterm"] = ""
                row["Final"] = ""

                avg, remarks = compute_average([q1, q2, q3, q4])

                row["Final Term Grade"] = avg
                row["Remarks"] = "" if remarks == "NO GRADE" else remarks

            df = pd.concat(
                [df, pd.DataFrame([row])],
                ignore_index=True
            )

        save_data(df)

        return redirect(f"/edit_grades/{student_id}")

    return render_template(
        "add_grade.html",
        student=student,
        student_level=student_level,
        show_value=show_value
    )

@app.route("/edit_grades/<student_id>", methods=["GET", "POST"])
def edit_grades(student_id):
    df = load_data()

    student_records = df[
        df["Student ID"].astype(str) == str(student_id)
    ]

    if student_records.empty:
        return "No records found"

    student = student_records.iloc[0].to_dict()
    grade_level = str(student.get("Grade Level", ""))

    if is_college(grade_level):
        student_level = "COLLEGE"
    elif is_shs(grade_level):
        student_level = "SHS"
    else:
        student_level = "JHS"

    def safe_grade(value):
        try:
            if value is None:
                return None

            value = str(value).strip()

            if value == "":
                return None

            return float(value)

        except:
            return None

    if request.method == "POST":
        row_indexes = request.form.getlist("row_index[]")

        for row_index in row_indexes:
            idx = int(row_index)

            if student_level == "COLLEGE":
                midterm = request.form.get(f"midterm_{idx}", "")
                final = request.form.get(f"final_{idx}", "")

                basis_grade = final if str(final).strip() != "" else midterm

                df.loc[idx, "Midterm"] = midterm
                df.loc[idx, "Final"] = final
                df.loc[idx, "Final Term Grade"] = basis_grade
                df.loc[idx, "Remarks"] = compute_college_remarks(basis_grade)

            elif student_level == "SHS":
                midterm = request.form.get(f"midterm_{idx}", "")
                final = request.form.get(f"final_{idx}", "")

                midterm_value = safe_grade(midterm)
                final_value = safe_grade(final)

                df.loc[idx, "Midterm"] = midterm_value
                df.loc[idx, "Final"] = final_value

                avg, remarks = compute_average([
                    midterm_value,
                    final_value
                ])

                df.loc[idx, "Final Term Grade"] = safe_grade(avg)
                df.loc[idx, "Remarks"] = (
                    ""
                    if remarks == "NO GRADE"
                    else remarks
                )

            else:
                q1 = request.form.get(f"q1_{idx}", "")
                q2 = request.form.get(f"q2_{idx}", "")
                q3 = request.form.get(f"q3_{idx}", "")
                q4 = request.form.get(f"q4_{idx}", "")

                q1_value = safe_grade(q1)
                q2_value = safe_grade(q2)
                q3_value = safe_grade(q3)
                q4_value = safe_grade(q4)

                df.loc[idx, "Q1"] = q1_value
                df.loc[idx, "Q2"] = q2_value
                df.loc[idx, "Q3"] = q3_value
                df.loc[idx, "Q4"] = q4_value

                avg, remarks = compute_average([
                    q1_value,
                    q2_value,
                    q3_value,
                    q4_value
                ])

                df.loc[idx, "Final Term Grade"] = safe_grade(avg)
                df.loc[idx, "Remarks"] = (
                    ""
                    if remarks == "NO GRADE"
                    else remarks
                )

        save_data(df)

        return redirect(f"/edit_grades/{student_id}")

    grouped_records = {}

    for idx, row in student_records.iterrows():
        row_dict = row.to_dict()
        row_dict["index"] = idx
        row_dict["Subject_Display"] = get_subject(row_dict)

        term = normalize_term(row.get("Term", ""))

        title = f"AY {row.get('Academic Year', '')} - {term}"

        if title not in grouped_records:
            grouped_records[title] = []

        grouped_records[title].append(row_dict)

    return render_template(
        "edit_grades.html",
        student=student,
        grouped_records=grouped_records,
        student_level=student_level,
        show_value=show_value
    )

@app.route("/grades")
def grades():
    df = load_data()
    df = filter_data_by_role(df)

    if df.empty:
        return render_template(
            "grades.html",
            matched_students=pd.DataFrame(),
            grouped_records={},
            show_value=show_value
        )

    search = request.args.get("search", "")
    selected_id = request.args.get("student_id", "")

    matched_students = pd.DataFrame()
    grouped_records = {}

    if search and not selected_id:
        matched_students = df[
            df["Full Name"].astype(str).str.contains(search, case=False, na=False)
            |
            df["Student ID"].astype(str).str.contains(search, case=False, na=False)
        ].drop_duplicates(subset=["Student ID"])

    if selected_id:
        student_df = df[
            df["Student ID"].astype(str) == str(selected_id)
        ]

        for _, row in student_df.iterrows():
            row_dict = row.to_dict()
            grade_level = str(row_dict.get("Grade Level", ""))

            if is_college(grade_level):
                row_dict["Type"] = "COLLEGE"
                term = str(row_dict.get("Term", "")).strip()
            elif is_shs(grade_level):
                row_dict["Type"] = "SHS"
                term = normalize_term(row_dict.get("Term", ""))
            else:
                row_dict["Type"] = "JHS"
                term = normalize_term(row_dict.get("Term", ""))

            row_dict["Subject_Display"] = get_subject(row_dict)

            if term == "":
                term = "No Term"

            group_title = (
                f'{row_dict.get("Full Name", "")} | '
                f'{row_dict.get("Grade Level", "")} | '
                f'AY {row_dict.get("Academic Year", "")} - '
                f'{term}'
            )

            if group_title not in grouped_records:
                grouped_records[group_title] = []

            grouped_records[group_title].append(row_dict)

    return render_template(
        "grades.html",
        matched_students=matched_students,
        grouped_records=grouped_records,
        show_value=show_value
    )


@app.route("/export_pdf")
def export_pdf():
    df = load_data()
    df = filter_data_by_role(df)

    if df.empty:
        return "No data available"

    df = normalize_all_terms(df)

    level = request.args.get("level", "ALL").upper()
    sport = request.args.get("sport", "")
    term = normalize_term(request.args.get("term", ""))
    academic_year = request.args.get("academic_year", "")
    grade_level = request.args.get("grade_level", "")

    if session.get("role") == "admin_college":
        level = "COLLEGE"
        grade_level = "College"

    if level == "JHS":
        df = df[df["Grade Level"].astype(str).str.contains("Grade 7|Grade 8|Grade 9|Grade 10", na=False)]
        report_type = "JHS Grade Report"

    elif level == "SHS":
        df = df[df["Grade Level"].astype(str).str.contains("Grade 11|Grade 12", na=False)]
        report_type = "SHS Grade Report"

    elif level == "COLLEGE":
        df = df[df["Grade Level"].astype(str).str.contains("College", case=False, na=False)]
        report_type = "College Grade Report"

    else:
        report_type = "All Students Grade Report"

    if sport:
        df = df[df["Sports Events"].astype(str) == sport]

    if term:
        df = df[df["Term"].astype(str).apply(normalize_term) == term]

    if academic_year:
        df = df[df["Academic Year"].astype(str) == academic_year]

    if grade_level:
        df = df[df["Grade Level"].astype(str) == grade_level]

    if df.empty:
        return "No records found for the selected filters"

    df["Subject_Display"] = df.apply(lambda row: get_subject(row), axis=1)

    df = df.sort_values(
        by=["Full Name", "Academic Year", "Term", "Sports Events", "Subject_Display"],
        na_position="last"
    )

    buffer = BytesIO()

    doc = SimpleDocTemplate(
        buffer,
        pagesize=landscape(legal),
        rightMargin=10,
        leftMargin=10,
        topMargin=10,
        bottomMargin=10
    )

    styles = getSampleStyleSheet()

    title_style = ParagraphStyle(
        "TitleStyle",
        parent=styles["Heading2"],
        fontSize=12,
        leading=14,
        alignment=TA_CENTER,
        spaceAfter=4
    )

    small_style = ParagraphStyle(
        "SmallStyle",
        parent=styles["Normal"],
        fontSize=6,
        leading=7,
        alignment=TA_CENTER
    )

    left_style = ParagraphStyle(
        "LeftStyle",
        parent=styles["Normal"],
        fontSize=6,
        leading=7,
        alignment=TA_LEFT
    )

    subject_style = ParagraphStyle(
        "SubjectStyle",
        parent=styles["Normal"],
        fontSize=6,
        leading=7,
        alignment=TA_LEFT
    )

    center_style = ParagraphStyle(
        "CenterStyle",
        parent=styles["Normal"],
        fontSize=6,
        leading=7,
        alignment=TA_CENTER
    )

    def remarks_paragraph(value):
        value = str(value).strip().upper()

        if value in ["PASSED", "PASS"]:
            return Paragraph('<font color="green"><b>PASSED</b></font>', center_style)

        if value in ["FAILED", "REPEAT", "DROPPED", "DROP"]:
            return Paragraph(f'<font color="red"><b>{value}</b></font>', center_style)

        if value in ["INC", "INCOMPLETE", "NO GRADE"]:
            return Paragraph(f'<font color="orange"><b>{value}</b></font>', center_style)

        return Paragraph(f"<b>{value}</b>", center_style)

    elements = []

    logo_path = "static/nu_logo.png"
    if os.path.exists(logo_path):
        elements.append(Image(logo_path, width=260, height=60))

    display_ay = academic_year if academic_year else "All Academic Years"
    display_term = term if term else "All Terms"
    display_sport = sport if sport else "All Sports"

    elements.append(Spacer(1, 4))
    elements.append(Paragraph(report_type.upper(), title_style))
    elements.append(
        Paragraph(
            f"AY: {display_ay} | Term: {display_term} | Sport: {display_sport}",
            small_style
        )
    )
    elements.append(Spacer(1, 8))

    headers = [
        "Student ID",
        "Full Name",
        "Level",
        "Sport",
        "AY",
        "Term",
        "Period",
        "Subject",
        "Grade",
        "Remarks"
    ]

    col_widths = [65, 115, 50, 85, 55, 50, 55, 285, 50, 75]

    table_data = [headers]
    span_ranges = []
    grouped = {}

    for _, row in df.iterrows():
        student_id = str(show_value(row.get("Student ID")))
        full_name = str(show_value(row.get("Full Name")))
        level_value = str(show_value(row.get("Grade Level")))
        sport_value = str(show_value(row.get("Sports Events")))
        ay_value = str(show_value(row.get("Academic Year")))
        term_value = normalize_term(row.get("Term", ""))

        subject = get_subject(row)

        if subject.strip() == "":
            continue

        key = (
            student_id,
            full_name,
            level_value,
            sport_value,
            ay_value
        )

        q1 = number_or_blank(row.get("Q1"))
        q2 = number_or_blank(row.get("Q2"))
        q3 = number_or_blank(row.get("Q3"))
        q4 = number_or_blank(row.get("Q4"))
        midterm = number_or_blank(row.get("Midterm"))
        final = number_or_blank(row.get("Final"))

        if is_college(level_value):
            if str(final).strip() != "":
                period = "Final"
                grade_display = final
            elif str(midterm).strip() != "":
                period = "Midterm"
                grade_display = midterm
            else:
                period = "No Grade"
                grade_display = ""

            remarks_display = compute_college_remarks(grade_display)

            if remarks_display == "":
                remarks_display = "NO GRADE"

        elif is_shs(level_value):
            period = "Average"
            grade_display, remarks_display = compute_average([midterm, final])

        else:
            period = "Average"
            grade_display, remarks_display = compute_average([q1, q2, q3, q4])

        if key not in grouped:
            grouped[key] = []

        grouped[key].append({
            "term": term_value,
            "period": period,
            "subject": subject,
            "grade": grade_display,
            "remarks": remarks_display
        })

    for key, subjects in grouped.items():
        student_id, full_name, level_value, sport_value, ay_value = key

        start_row = len(table_data)

        for i, subject in enumerate(subjects):
            if i == 0:
                row_data = [
                    Paragraph(student_id, center_style),
                    Paragraph(full_name, left_style),
                    Paragraph(level_value, center_style),
                    Paragraph(sport_value, center_style),
                    Paragraph(ay_value, center_style),
                    Paragraph(subject["term"], center_style),
                    Paragraph(subject["period"], center_style),
                    Paragraph(subject["subject"], subject_style),
                    Paragraph(str(subject["grade"]), center_style),
                    remarks_paragraph(subject["remarks"])
                ]
            else:
                row_data = [
                    "",
                    "",
                    "",
                    "",
                    "",
                    Paragraph(subject["term"], center_style),
                    Paragraph(subject["period"], center_style),
                    Paragraph(subject["subject"], subject_style),
                    Paragraph(str(subject["grade"]), center_style),
                    remarks_paragraph(subject["remarks"])
                ]

            table_data.append(row_data)

        end_row = len(table_data) - 1

        if end_row > start_row:
            for col in range(0, 5):
                span_ranges.append((col, start_row, end_row))

    if len(table_data) == 1:
        return "No grade records found for the selected filters"

    table = Table(
        table_data,
        repeatRows=1,
        colWidths=col_widths
    )

    report_table_style = TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#2f63b7")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, 0), 6),
        ("FONTSIZE", (0, 1), (-1, -1), 5.8),
        ("GRID", (0, 0), (-1, -1), 0.35, colors.black),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("ALIGN", (1, 1), (1, -1), "LEFT"),
        ("ALIGN", (7, 1), (7, -1), "LEFT"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("LEFTPADDING", (0, 0), (-1, -1), 3),
        ("RIGHTPADDING", (0, 0), (-1, -1), 3),
    ])

    for col, start_row, end_row in span_ranges:
        report_table_style.add("SPAN", (col, start_row), (col, end_row))
        report_table_style.add("VALIGN", (col, start_row), (col, end_row), "MIDDLE")

    table.setStyle(report_table_style)

    elements.append(table)
    elements.append(Spacer(1, 25))

    signature_data = [[
        Paragraph(
            "<b>Prepared By:</b><br/><br/>"
            "______________________________<br/>"
            f"{session.get('fullname', '')}<br/>"
            f"{session.get('position', '')}",
            small_style
        ),
        Paragraph(
            "<b>Reviewed By:</b><br/><br/>"
            "______________________________<br/>"
            "Ms. Maria Ester V. Suarez<br/>"
            "Assistant Director, AADO",
            small_style
        )
    ]]

    signature_table = Table(signature_data, colWidths=[440, 440])
    signature_table.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("ALIGN", (0, 0), (0, 0), "LEFT"),
        ("ALIGN", (1, 0), (1, 0), "RIGHT"),
    ]))

    elements.append(signature_table)

    doc.build(elements)

    pdf = buffer.getvalue()
    buffer.close()

    response = make_response(pdf)
    response.headers["Content-Type"] = "application/pdf"
    response.headers["Content-Disposition"] = (
        "attachment; filename=grades_report.pdf"
    )

    return response

@app.route("/intervention_report")
def intervention_report():
    df = load_data()
    df = filter_data_by_role(df)

    if df.empty:
        return "No data available"

    df = normalize_all_terms(df)

    report_type = request.args.get("type", "remedial")
    level = request.args.get("level", "ALL").upper()
    sport = request.args.get("sport", "")
    term = normalize_term(request.args.get("term", ""))
    academic_year = request.args.get("academic_year", "")
    grade_level_filter = request.args.get("grade_level", "")

    if level == "JHS":
        df = df[
            df["Grade Level"].astype(str).str.contains(
                "Grade 7|Grade 8|Grade 9|Grade 10",
                na=False
            )
        ]

    elif level == "SHS":
        df = df[
            df["Grade Level"].astype(str).str.contains(
                "Grade 11|Grade 12",
                na=False
            )
        ]

    elif level == "COLLEGE":
        df = df[
            df["Grade Level"].astype(str).str.contains(
                "College",
                case=False,
                na=False
            )
        ]

    if sport:
        df = df[df["Sports Events"].astype(str) == sport]

    if term:
        df = df[
            df["Term"].astype(str).apply(normalize_term) == term
        ]

    if academic_year:
        df = df[df["Academic Year"].astype(str) == academic_year]

    if grade_level_filter:
        df = df[df["Grade Level"].astype(str) == grade_level_filter]

    if df.empty:
        return "No records found for the selected filters"

    df["Subject_Display"] = df.apply(lambda row: get_subject(row), axis=1)

    df = df.sort_values(
        by=["Full Name", "Academic Year", "Term", "Sports Events", "Subject_Display"],
        na_position="last"
    )

    grouped = {}

    for _, row in df.iterrows():
        grade_level = str(row.get("Grade Level", ""))
        subject = get_subject(row)

        if subject.strip() == "":
            continue

        q1 = number_or_blank(row.get("Q1"))
        q2 = number_or_blank(row.get("Q2"))
        q3 = number_or_blank(row.get("Q3"))
        q4 = number_or_blank(row.get("Q4"))
        midterm = number_or_blank(row.get("Midterm"))
        final = number_or_blank(row.get("Final"))

        period = ""
        grade_display = ""
        status = ""

        if is_college(grade_level):
            if str(final).strip() != "":
                period = "Final"
                grade_display = final
            elif str(midterm).strip() != "":
                period = "Midterm"
                grade_display = midterm
            else:
                continue

            status = compute_college_remarks(grade_display)

            if report_type == "remedial":
                continue

            if status not in ["FAILED", "REPEAT", "INCOMPLETE", "DROPPED"]:
                continue

            intervention_status = status

        else:
            period = "Average"

            if is_shs(grade_level):
                average, _ = compute_average([midterm, final])
            else:
                average, _ = compute_average([q1, q2, q3, q4])

            if average == "":
                continue

            grade_num = float(average)
            grade_display = int(round(grade_num))

            if report_type == "remedial":
                if not (71 <= grade_num <= 74):
                    continue
                intervention_status = "REMEDIAL"

            elif report_type == "load_revision":
                if not (grade_num <= 70):
                    continue
                intervention_status = "LOAD REVISION"

            else:
                continue

        student_id = str(show_value(row.get("Student ID")))
        full_name = str(show_value(row.get("Full Name")))
        level_value = str(show_value(row.get("Grade Level")))
        sport_value = str(show_value(row.get("Sports Events")))
        ay_value = str(show_value(row.get("Academic Year")))

        key = (
            student_id,
            full_name,
            level_value,
            sport_value,
            ay_value
        )

        if key not in grouped:
            grouped[key] = []

        grouped[key].append({
            "term": normalize_term(row.get("Term", "")),
            "period": period,
            "subject": subject,
            "grade": grade_display,
            "remarks": intervention_status
        })

    if not grouped:
        return "No intervention records found for the selected filters"

    title = (
        "Remedial Report"
        if report_type == "remedial"
        else "Load Revision / Deficiency Report"
    )

    filename = (
        "remedial_report.pdf"
        if report_type == "remedial"
        else "load_revision_deficiency_report.pdf"
    )

    buffer = BytesIO()

    doc = SimpleDocTemplate(
        buffer,
        pagesize=landscape(legal),
        rightMargin=10,
        leftMargin=10,
        topMargin=10,
        bottomMargin=10
    )

    styles = getSampleStyleSheet()

    title_style = ParagraphStyle(
        "TitleStyle",
        parent=styles["Heading2"],
        fontSize=12,
        leading=14,
        alignment=TA_CENTER,
        spaceAfter=4
    )

    small_style = ParagraphStyle(
        "SmallStyle",
        parent=styles["Normal"],
        fontSize=6,
        leading=7,
        alignment=TA_CENTER
    )

    left_style = ParagraphStyle(
        "LeftStyle",
        parent=styles["Normal"],
        fontSize=6,
        leading=7,
        alignment=TA_LEFT
    )

    subject_style = ParagraphStyle(
        "SubjectStyle",
        parent=styles["Normal"],
        fontSize=6,
        leading=7,
        alignment=TA_LEFT
    )

    center_style = ParagraphStyle(
        "CenterStyle",
        parent=styles["Normal"],
        fontSize=6,
        leading=7,
        alignment=TA_CENTER
    )

    elements = []

    logo_path = "static/nu_logo.png"

    if os.path.exists(logo_path):
        logo = Image(logo_path, width=260, height=60)
        elements.append(logo)

    display_ay = academic_year if academic_year else "All Academic Years"
    display_term = term if term else "All Terms"
    display_sport = sport if sport else "All Sports"

    elements.append(Spacer(1, 4))
    elements.append(Paragraph(title.upper(), title_style))
    elements.append(
        Paragraph(
            f"AY: {display_ay} | Term: {display_term} | Sport: {display_sport}",
            small_style
        )
    )
    elements.append(Spacer(1, 8))

    headers = [
        "Student ID",
        "Full Name",
        "Level",
        "Sport",
        "AY",
        "Term",
        "Period",
        "Subject",
        "Grade",
        "Remarks"
    ]

    col_widths = [65, 115, 50, 85, 55, 50, 55, 285, 50, 75]

    table_data = [headers]
    span_ranges = []

    for key, subjects in grouped.items():
        student_id, full_name, level_value, sport_value, ay_value = key

        start_row = len(table_data)

        for i, subject in enumerate(subjects):
            if i == 0:
                row_data = [
                    Paragraph(student_id, center_style),
                    Paragraph(full_name, left_style),
                    Paragraph(level_value, center_style),
                    Paragraph(sport_value, center_style),
                    Paragraph(ay_value, center_style),
                    Paragraph(subject["term"], center_style),
                    Paragraph(subject["period"], center_style),
                    Paragraph(subject["subject"], subject_style),
                    Paragraph(str(subject["grade"]), center_style),
                    Paragraph(str(subject["remarks"]), center_style)
                ]
            else:
                row_data = [
                    "",
                    "",
                    "",
                    "",
                    "",
                    Paragraph(subject["term"], center_style),
                    Paragraph(subject["period"], center_style),
                    Paragraph(subject["subject"], subject_style),
                    Paragraph(str(subject["grade"]), center_style),
                    Paragraph(str(subject["remarks"]), center_style)
                ]

            table_data.append(row_data)

        end_row = len(table_data) - 1

        if end_row > start_row:
            for col in range(0, 5):
                span_ranges.append((col, start_row, end_row))

    table = Table(
        table_data,
        repeatRows=1,
        colWidths=col_widths
    )

    table_style = TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#2f63b7")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, 0), 6),
        ("FONTSIZE", (0, 1), (-1, -1), 5.8),
        ("GRID", (0, 0), (-1, -1), 0.35, colors.black),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("ALIGN", (1, 1), (1, -1), "LEFT"),
        ("ALIGN", (7, 1), (7, -1), "LEFT"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("LEFTPADDING", (0, 0), (-1, -1), 3),
        ("RIGHTPADDING", (0, 0), (-1, -1), 3),
    ])

    for col, start_row, end_row in span_ranges:
        table_style.add("SPAN", (col, start_row), (col, end_row))
        table_style.add("VALIGN", (col, start_row), (col, end_row), "MIDDLE")

    remarks_col = 9

    for row_index in range(1, len(table_data)):
        remark_cell = table_data[row_index][remarks_col]

        try:
            remark = str(remark_cell.text).upper().strip()
        except:
            remark = str(remark_cell).upper().strip()

        if remark in ["REMEDIAL", "INCOMPLETE", "NO GRADE"]:
            table_style.add("TEXTCOLOR", (remarks_col, row_index), (remarks_col, row_index), colors.orange)

        elif remark in ["LOAD REVISION", "FAILED", "REPEAT", "DROPPED", "DROP"]:
            table_style.add("TEXTCOLOR", (remarks_col, row_index), (remarks_col, row_index), colors.red)

        table_style.add("FONTNAME", (remarks_col, row_index), (remarks_col, row_index), "Helvetica-Bold")

    table.setStyle(table_style)

    elements.append(table)
    elements.append(Spacer(1, 25))

    signature_data = [[
        Paragraph(
            "<b>Prepared By:</b><br/><br/>"
            "______________________________<br/>"
            f"{session.get('fullname', '')}<br/>"
            f"{session.get('position', '')}",
            small_style
        ),
        Paragraph(
            "<b>Reviewed By:</b><br/><br/>"
            "______________________________<br/>"
            "Ms. Maria Ester V. Suarez<br/>"
            "Assistant Director, AADO",
            small_style
        )
    ]]

    signature_table = Table(signature_data, colWidths=[440, 440])
    signature_table.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("ALIGN", (0, 0), (0, 0), "LEFT"),
        ("ALIGN", (1, 0), (1, 0), "RIGHT"),
    ]))

    elements.append(signature_table)

    doc.build(elements)

    pdf = buffer.getvalue()
    buffer.close()

    response = make_response(pdf)
    response.headers["Content-Type"] = "application/pdf"
    response.headers["Content-Disposition"] = (
        f"attachment; filename={filename}"
    )

    return response

@app.route("/monitoring_form_filter/<student_id>")
def monitoring_form_filter(student_id):

    df = load_data()
    df = filter_data_by_role(df)

    student_records = df[
        df["Student ID"].astype(str) == str(student_id)
    ]

    if student_records.empty:
        return "Student not found"

    student = student_records.iloc[0].to_dict()
    grade_level = str(student.get("Grade Level", ""))

    academic_years = sorted(
        student_records["Academic Year"]
        .dropna()
        .astype(str)
        .unique()
    )

    # ==========================
    # COLLEGE
    # ==========================
    if is_college(grade_level):

        terms = [
            "Term 1",
            "Term 2",
            "Term 3"
        ]

        periods = [
            "Midterm",
            "Final"
        ]

    # ==========================
    # SHS
    # ==========================
    elif is_shs(grade_level):

        terms = sorted(
            student_records["Term"]
            .dropna()
            .astype(str)
            .apply(normalize_term)
            .unique()
        )

        periods = [
            "Average",
            "Midterm",
            "Final"
        ]

    # ==========================
    # JHS
    # ==========================
    else:

        terms = sorted(
            student_records["Term"]
            .dropna()
            .astype(str)
            .apply(normalize_term)
            .unique()
        )

        periods = [
            "Average",
            "Q1",
            "Q2",
            "Q3",
            "Q4"
        ]

    return render_template(
        "monitoring_form_filter.html",
        student=student,
        academic_years=academic_years,
        terms=terms,
        periods=periods
    )

@app.route("/academic_monitoring_form/<student_id>")
def academic_monitoring_form(student_id):

    df = load_data()
    df = filter_data_by_role(df)

    student_records = df[df["Student ID"].astype(str) == str(student_id)]

    if student_records.empty:
        return "Student not found"

    student = student_records.iloc[0].to_dict()
    grade_level = str(student.get("Grade Level", ""))

    academic_year = request.args.get("academic_year", "")
    term = request.args.get("term", "")
    period = request.args.get("period", "")
    remarks_input = request.args.get("remarks", "").strip()
    case_no = generate_case_no(grade_level)

    ph_time = datetime.now(ZoneInfo("Asia/Manila"))
    current_date = ph_time.strftime("%B %d, %Y")
    current_time = ph_time.strftime("%I:%M %p")

    def grade_is_failed(value):
        try:
            if value is None:
                return False
            value = str(value).strip()
            if value == "" or value.lower() == "nan":
                return False
            return float(value) < 75
        except:
            return False

    failed_records = []

    for _, row in student_records.iterrows():

        subject = get_subject(row)
        row_academic_year = str(show_value(row.get("Academic Year")))
        row_term = normalize_term(row.get("Term", ""))

        if academic_year and row_academic_year != academic_year:
            continue

        if term and row_term != normalize_term(term):
            continue

        if period == "Average":

            if is_shs(grade_level):
                values = [row.get("Midterm"), row.get("Final")]

            elif is_college(grade_level):
                values = [row.get("Final")]

            else:
                values = [
                    row.get("Q1"),
                    row.get("Q2"),
                    row.get("Q3"),
                    row.get("Q4")
                ]

            grades = []

            for value in values:
                try:
                    value = str(value).strip()
                    if value != "" and value.lower() != "nan":
                        grades.append(float(value))
                except:
                    pass

            if grades:
                average_raw = sum(grades) / len(grades)
                average_grade = int(average_raw + 0.5)

                if average_grade < 75:
                    failed_records.append([
                        row_academic_year,
                        row_term,
                        "Average",
                        subject,
                        number_or_blank(average_grade),
                        "",
                        ""
                    ])

        else:

            if is_college(grade_level):
                periods_to_check = ["Final"] if not period else [period]

            elif is_shs(grade_level):
                periods_to_check = ["Midterm", "Final"] if not period else [period]

            else:
                periods_to_check = ["Q1", "Q2", "Q3", "Q4"] if not period else [period]

            for p in periods_to_check:
                grade = row.get(p)

                if grade_is_failed(grade):
                    failed_records.append([
                        row_academic_year,
                        row_term,
                        p,
                        subject,
                        number_or_blank(grade),
                        "",
                        ""
                    ])

    if not failed_records:
        failed_records.append([
            "-",
            "-",
            "-",
            "No failed subjects found",
            "-",
            "",
            ""
        ])

    buffer = BytesIO()

    doc = SimpleDocTemplate(
        buffer,
        pagesize=landscape(legal),
        rightMargin=12,
        leftMargin=12,
        topMargin=85,
        bottomMargin=10
    )

    styles = getSampleStyleSheet()

    normal = ParagraphStyle(
        "NormalSmall",
        parent=styles["Normal"],
        fontSize=7.5,
        leading=9
    )

    small = ParagraphStyle(
        "Small",
        parent=styles["Normal"],
        fontSize=6.8,
        leading=8
    )

    section_style = ParagraphStyle(
        "SectionStyle",
        parent=styles["Normal"],
        fontSize=8,
        leading=9,
        alignment=TA_CENTER,
        textColor=colors.white
    )

    title_style = ParagraphStyle(
        "TitleStyle",
        parent=styles["Heading1"],
        alignment=TA_CENTER,
        fontSize=16,
        leading=18,
        spaceAfter=3
    )

    checkbox_style = ParagraphStyle(
        "CheckboxStyle",
        parent=styles["Normal"],
        fontSize=8,
        leading=10
    )

    def checkbox_label(text, line=False):
        label = text

        if line:
            label = text + " __________________"

        checkbox = Drawing(12, 12)
        checkbox.add(
            Rect(
                1,
                1,
                10,
                10,
                strokeColor=colors.black,
                fillColor=None,
                strokeWidth=0.8
            )
        )

        item = Table(
            [[checkbox, Paragraph(label, checkbox_style)]],
            colWidths=[18, 210]
        )

        item.setStyle(TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("LEFTPADDING", (0, 0), (-1, -1), 0),
            ("RIGHTPADDING", (0, 0), (-1, -1), 0),
            ("TOPPADDING", (0, 0), (-1, -1), 0),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
        ]))

        return item

    def draw_header(canvas, doc):
        canvas.saveState()

        logo_path = "static/nu_logo.png"

        if os.path.exists(logo_path):
            logo = Image(logo_path, width=250, height=55)
        else:
            logo = Paragraph(
                "NATIONAL UNIVERSITY<br/>Athletes' Academic Development Office",
                normal
            )

        header_info = Table(
            [[
                Paragraph("<b>Case No.:</b><br/>" + case_no, normal),
                Paragraph("<b>Date Generated:</b><br/>" + current_date, normal),
                Paragraph("<b>Time Generated:</b><br/>" + current_time, normal),
            ]],
            colWidths=[210, 210, 210]
        )

        header_info.setStyle(TableStyle([
            ("GRID", (0, 0), (-1, -1), 0.5, colors.black),
            ("ALIGN", (0, 0), (-1, -1), "CENTER"),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("PADDING", (0, 0), (-1, -1), 5),
        ]))

        header_table = Table(
            [
                [
                    logo,
                    Paragraph("ACADEMIC MONITORING AND ADVISING FORM", title_style),
                ],
                [
                    "",
                    header_info
                ]
            ],
            colWidths=[310, 650]
        )

        header_table.setStyle(TableStyle([
            ("SPAN", (0, 0), (0, 1)),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("ALIGN", (1, 0), (1, 0), "CENTER"),
        ]))

        header_table.wrap(doc.width, doc.topMargin)
        header_table.drawOn(canvas, doc.leftMargin, doc.pagesize[1] - 75)

        canvas.restoreState()

    def section_bar(title):
        t = Table(
            [[Paragraph(f"<b>{title}</b>", section_style)]],
            colWidths=[960]
        )
        t.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#082b87")),
            ("PADDING", (0, 0), (-1, -1), 4),
        ]))
        return t

    coverage_year = academic_year if academic_year else "All Academic Years"
    coverage_term = normalize_term(term) if term else "All Terms"
    coverage_period = period if period else "All Periods"

    elements = []

    elements.append(section_bar("STUDENT INFORMATION"))

    info_data = [
        [
            Paragraph("<b>Student Name</b>", normal),
            Paragraph(str(show_value(student.get("Full Name"))), normal),
            Paragraph("<b>Student ID No.</b>", normal),
            Paragraph(str(show_value(student.get("Student ID"))), normal),
        ],
        [
            Paragraph("<b>Grade Level</b>", normal),
            Paragraph(str(show_value(student.get("Grade Level"))), normal),
            Paragraph("<b>Section / Strand</b>", normal),
            Paragraph(f"{show_value(student.get('Section'))} {show_value(student.get('Strand'))}", normal),
        ],
        [
            Paragraph("<b>Sport</b>", normal),
            Paragraph(str(show_value(student.get("Sports Events"))), normal),
            Paragraph("<b>Monitoring Coverage</b>", normal),
            Paragraph(f"{coverage_year} | {coverage_term} | {coverage_period}", normal),
        ],
        [
            Paragraph("<b>Date / Time</b>", normal),
            Paragraph(f"{current_date} - {current_time}", normal),
            Paragraph("<b>Monitoring Type</b>", normal),
            Paragraph("Academic Deficiency Record", normal),
        ],
    ]

    info_table = Table(info_data, colWidths=[120, 350, 135, 355])
    info_table.setStyle(TableStyle([
        ("GRID", (0, 0), (-1, -1), 0.45, colors.black),
        ("BACKGROUND", (0, 0), (0, -1), colors.whitesmoke),
        ("BACKGROUND", (2, 0), (2, -1), colors.whitesmoke),
        ("PADDING", (0, 0), (-1, -1), 5),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
    ]))

    elements.append(info_table)
    elements.append(Spacer(1, 5))

    elements.append(section_bar("ADVISING CONCERNS DISCUSSED"))

    concerns_data = [
        [
            checkbox_label("Low Grades"),
            checkbox_label("Attendance Issues"),
            checkbox_label("Subject Enrollment"),
            checkbox_label("Study Habits"),
        ],
        [
            checkbox_label("Time Management"),
            checkbox_label("Personal Concerns"),
            checkbox_label("Career Guidance"),
            checkbox_label("Others", line=True),
        ],
    ]

    concerns_table = Table(concerns_data, colWidths=[240, 240, 240, 240])
    concerns_table.setStyle(TableStyle([
        ("GRID", (0, 0), (-1, -1), 0.45, colors.black),
        ("PADDING", (0, 0), (-1, -1), 7),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
    ]))

    elements.append(concerns_table)
    elements.append(Spacer(1, 5))

    elements.append(section_bar("ACADEMIC DEFICIENCY / MONITORING RECORD"))

    monitoring_headers = [
        "Academic Year",
        "Term",
        "Period",
        "Subject",
        "Grade",
        "Teacher Remarks",
        "Teacher Signature"
    ]

    monitoring_data = [monitoring_headers] + failed_records

    monitoring_table = Table(
        monitoring_data,
        repeatRows=1,
        colWidths=[85, 65, 65, 300, 50, 240, 155]
    )

    monitoring_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 7),
        ("GRID", (0, 0), (-1, -1), 0.45, colors.black),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("ALIGN", (0, 1), (2, -1), "CENTER"),
        ("ALIGN", (4, 1), (4, -1), "CENTER"),
        ("PADDING", (0, 0), (-1, -1), 4),
    ]))

    elements.append(monitoring_table)
    elements.append(Spacer(1, 5))

    elements.append(section_bar("INTERVENTION PLAN / ACTION TAKEN"))

    intervention_data = [
        [
            checkbox_label("Academic Consultation"),
            checkbox_label("Teacher Coordination"),
            checkbox_label("Coach Coordination"),
            checkbox_label("Parent / Guardian Conference"),
        ],
        [
            checkbox_label("Remedial Activity"),
            checkbox_label("Tutorial Assistance"),
            checkbox_label("Academic Monitoring"),
            checkbox_label("Others", line=True),
        ],
    ]

    intervention_table = Table(intervention_data, colWidths=[240, 240, 240, 240])
    intervention_table.setStyle(TableStyle([
        ("GRID", (0, 0), (-1, -1), 0.45, colors.black),
        ("PADDING", (0, 0), (-1, -1), 7),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
    ]))

    elements.append(intervention_table)
    elements.append(Spacer(1, 5))

    elements.append(section_bar("REMARKS AND STATUS"))

    status_table = Table(
        [
            [Paragraph("<b>Status:</b>", normal)],
            [checkbox_label("In Progress")],
            [checkbox_label("On Track")],
            [checkbox_label("At Risk")],
            [checkbox_label("Satisfactory Progress")],
            [checkbox_label("Outstanding Performance")],
        ],
        colWidths=[300]
    )

    status_table.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 1),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 1),
    ]))

    remarks_table = Table(
        [[
            Paragraph(
                "<b>Remarks:</b><br/><br/>" +
                (
                    remarks_input.replace("\n", "<br/>")
                    if remarks_input
                    else "_______________________________________________<br/><br/>_______________________________________________"
                ),
                normal
            ),
            status_table
        ]],
        colWidths=[580, 380]
    )

    remarks_table.setStyle(TableStyle([
        ("GRID", (0, 0), (-1, -1), 0.45, colors.black),
        ("PADDING", (0, 0), (-1, -1), 7),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
    ]))

    elements.append(remarks_table)
    elements.append(Spacer(1, 5))

    elements.append(section_bar("SIGNATORIES"))

    signature_data = [
        [
            Paragraph("Academic Adviser:<br/><br/>____________________________", normal),
            Paragraph("Student:<br/><br/>____________________________", normal),
            Paragraph("Head Coach / Asst. Coach:<br/><br/>____________________________", normal),
            Paragraph("Parent / Guardian:<br/><br/>____________________________", normal),
        ],
        [
            Paragraph(
                f"<b>Prepared By:</b><br/><br/>____________________________<br/>"
                f"{session.get('fullname', '')}<br/>"
                f"{session.get('position', '')}",
                small
            ),
            Paragraph(
                "<b>Reviewed and Approved By:</b><br/><br/>____________________________<br/>"
                "Ms. Maria Ester V. Suarez<br/>"
                "Assistant Director, AADO",
                small
            ),
            "",
            ""
        ]
    ]

    signature_table = Table(signature_data, colWidths=[240, 240, 240, 240])
    signature_table.setStyle(TableStyle([
        ("GRID", (0, 0), (-1, -1), 0.45, colors.black),
        ("SPAN", (1, 1), (3, 1)),
        ("PADDING", (0, 0), (-1, -1), 7),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
    ]))

    elements.append(signature_table)

    doc.build(
        elements,
        onFirstPage=draw_header,
        onLaterPages=draw_header
    )

    pdf = buffer.getvalue()
    buffer.close()

    response = make_response(pdf)
    response.headers["Content-Type"] = "application/pdf"
    response.headers["Content-Disposition"] = (
        f"attachment; filename=academic_monitoring_{student_id}.pdf"
    )

    return response


@app.route("/college_deficiency_report")
def college_deficiency_report():
    df = load_data()
    df = filter_data_by_role(df)

    if df.empty:
        return "No data available"

    df = df[
        df["Grade Level"]
        .astype(str)
        .str.contains("College", case=False, na=False)
    ]

    if df.empty:
        return "No college records available"

    academic_year = request.args.get("academic_year", "")
    term = request.args.get("term", "")
    sport = request.args.get("sport", "")

    if academic_year:
        df = df[df["Academic Year"].astype(str) == academic_year]

    if term:
        df = df[df["Term"].astype(str) == term]

    if sport:
        df = df[df["Sports Events"].astype(str) == sport]

    deficiency_rows = []

    for _, row in df.iterrows():
        final_grade = str(row.get("Final", "")).strip().upper()

        status = ""

        if final_grade in ["5", "5.0", "5.00", "0", "0.0", "0.00"]:
            status = "FAILED"
        elif final_grade == "INC":
            status = "INCOMPLETE"
        elif final_grade == "R":
            status = "REPEAT"
        elif final_grade == "DROP":
            status = "DROPPED"

        if status:
            deficiency_rows.append([
                str(show_value(row.get("Student ID"))),
                str(show_value(row.get("Full Name"))),
                str(show_value(row.get("Course / Program"))),
                str(show_value(row.get("Year Level"))),
                str(show_value(row.get("Sports Events"))),
                str(show_value(row.get("Academic Year"))),
                str(show_value(row.get("Term"))),
                str(get_subject(row)),
                str(show_value(row.get("Midterm"))),
                str(show_value(row.get("Final"))),
                status
            ])

    deficiency_rows = sorted(
        deficiency_rows,
        key=lambda x: (
            x[1].lower(),
            x[5],
            x[6],
            x[7].lower()
        )
    )

    total_failed = sum(1 for r in deficiency_rows if r[10] == "FAILED")
    total_inc = sum(1 for r in deficiency_rows if r[10] == "INCOMPLETE")
    total_repeat = sum(1 for r in deficiency_rows if r[10] == "REPEAT")
    total_drop = sum(1 for r in deficiency_rows if r[10] == "DROPPED")

    buffer = BytesIO()

    doc = SimpleDocTemplate(
        buffer,
        pagesize=landscape(legal),
        rightMargin=10,
        leftMargin=10,
        topMargin=10,
        bottomMargin=10
    )

    styles = getSampleStyleSheet()

    title_style = ParagraphStyle(
        "TitleStyle",
        parent=styles["Heading2"],
        fontSize=12,
        leading=14,
        alignment=TA_CENTER,
        spaceAfter=6
    )

    normal_style = ParagraphStyle(
        "NormalSmall",
        parent=styles["Normal"],
        fontSize=7,
        leading=8
    )

    table_style_text = ParagraphStyle(
        "TableText",
        parent=styles["Normal"],
        fontSize=5.8,
        leading=6.5,
        alignment=TA_LEFT
    )

    table_center_text = ParagraphStyle(
        "TableCenterText",
        parent=styles["Normal"],
        fontSize=5.8,
        leading=6.5,
        alignment=TA_CENTER
    )

    elements = []

    logo_path = "static/nu_logo.png"

    if os.path.exists(logo_path):
        logo = Image(logo_path, width=260, height=60)
        elements.append(logo)

    elements.append(Spacer(1, 5))

    elements.append(
        Paragraph(
            "COLLEGE ACADEMIC DEFICIENCY REPORT",
            title_style
        )
    )

    summary = f"""
    <b>Total Deficiency Records:</b> {len(deficiency_rows)}<br/>
    <b>Failed:</b> {total_failed} &nbsp;&nbsp;
    <b>INC:</b> {total_inc} &nbsp;&nbsp;
    <b>Repeat:</b> {total_repeat} &nbsp;&nbsp;
    <b>Dropped:</b> {total_drop}
    """

    elements.append(Paragraph(summary, normal_style))
    elements.append(Spacer(1, 8))

    data = [[
        "Student ID",
        "Full Name",
        "Course",
        "Year",
        "Sport",
        "AY",
        "Term",
        "Subject",
        "Midterm",
        "Final",
        "Status"
    ]]

    for r in deficiency_rows:
        data.append([
            Paragraph(r[0], table_center_text),
            Paragraph(r[1], table_style_text),
            Paragraph(r[2], table_style_text),
            Paragraph(r[3], table_center_text),
            Paragraph(r[4], table_style_text),
            Paragraph(r[5], table_center_text),
            Paragraph(r[6], table_center_text),
            Paragraph(r[7], table_style_text),
            Paragraph(r[8], table_center_text),
            Paragraph(r[9], table_center_text),
            Paragraph(r[10], table_center_text),
        ])

    table = Table(
        data,
        repeatRows=1,
        colWidths=[58, 105, 125, 45, 85, 58, 48, 210, 48, 45, 70]
    )

    table_style = TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, 0), 6),
        ("FONTSIZE", (0, 1), (-1, -1), 5.8),
        ("GRID", (0, 0), (-1, -1), 0.35, colors.black),
        ("ALIGN", (0, 0), (-1, 0), "CENTER"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 2),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
        ("LEFTPADDING", (0, 0), (-1, -1), 2),
        ("RIGHTPADDING", (0, 0), (-1, -1), 2),
    ])

    status_col = 10

    for i in range(1, len(data)):
        status = deficiency_rows[i - 1][10].upper()

        if status == "FAILED":
            table_style.add("TEXTCOLOR", (status_col, i), (status_col, i), colors.red)
        elif status == "INCOMPLETE":
            table_style.add("TEXTCOLOR", (status_col, i), (status_col, i), colors.orange)
        elif status == "REPEAT":
            table_style.add("TEXTCOLOR", (status_col, i), (status_col, i), colors.purple)
        elif status == "DROPPED":
            table_style.add("TEXTCOLOR", (status_col, i), (status_col, i), colors.red)

        table_style.add("FONTNAME", (status_col, i), (status_col, i), "Helvetica-Bold")

    table.setStyle(table_style)
    elements.append(table)

    elements.append(Spacer(1, 25))

    signature_data = [[
        Paragraph(
            "<b>Prepared By:</b><br/><br/>"
            "______________________________<br/>"
            f"{session.get('fullname', '')}<br/>"
            f"{session.get('position', '')}",
            normal_style
        ),
        Paragraph(
            "<b>Reviewed By:</b><br/><br/>"
            "______________________________<br/>"
            "Ms. Maria Ester V. Suarez<br/>"
            "Assistant Director, AADO",
            normal_style
        )
    ]]

    signature_table = Table(signature_data, colWidths=[440, 440])
    signature_table.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("ALIGN", (0, 0), (0, 0), "LEFT"),
        ("ALIGN", (1, 0), (1, 0), "RIGHT"),
    ]))

    elements.append(signature_table)

    doc.build(elements)

    pdf = buffer.getvalue()
    buffer.close()

    response = make_response(pdf)
    response.headers["Content-Type"] = "application/pdf"
    response.headers["Content-Disposition"] = (
        "attachment; filename=college_deficiency_report.pdf"
    )

    return response

@app.route("/reports")
def reports():

    df = load_data()
    df = filter_data_by_role(df)

    if df.empty:
        return render_template(
            "reports.html",
            sports=[],
            jhs_sports=[],
            shs_sports=[],
            academic_years=[],
            terms=[],
            grade_levels=[],
            total_students=0,
            total_jhs=0,
            total_shs=0,
            total_college=0
        )

    df["Term"] = df["Term"].apply(normalize_term)

    role = session.get("role")

    if role == "admin_college":
        sports = get_sports_by_group("college")
    elif role == "admin_jhs_shs":
        sports = get_sports_by_group("basic_ed")
    else:
        sports = get_sports_by_group("basic_ed") + get_sports_by_group("college")

    sports = sorted(list(set(sports)))

    jhs_df = df[
        df["Grade Level"].astype(str).str.contains(
            "Grade 7|Grade 8|Grade 9|Grade 10",
            na=False
        )
    ]

    shs_df = df[
        df["Grade Level"].astype(str).str.contains(
            "Grade 11|Grade 12",
            na=False
        )
    ]

    jhs_sports = sorted(list(set(get_sports_by_group("basic_ed"))))
    shs_sports = sorted(list(set(get_sports_by_group("basic_ed"))))

    academic_years = sorted(
        df["Academic Year"]
        .dropna()
        .astype(str)
        .unique()
    )

    term_values = (
        df["Term"]
        .dropna()
        .astype(str)
        .apply(normalize_term)
        .unique()
    )

    term_order = [
        "1ST",
        "2ND",
        "3RD TERM",
        "4TH"
    ]

    terms = [
        term for term in term_order
        if term in term_values
    ]

    grade_levels = sorted(
        df["Grade Level"]
        .dropna()
        .astype(str)
        .unique()
    )

    students_unique = df.drop_duplicates(
        subset=["Student ID"]
    )

    total_students = len(students_unique)

    total_jhs = len(
        students_unique[
            students_unique["Grade Level"]
            .astype(str)
            .str.contains("Grade 7|Grade 8|Grade 9|Grade 10", na=False)
        ]
    )

    total_shs = len(
        students_unique[
            students_unique["Grade Level"]
            .astype(str)
            .str.contains("Grade 11|Grade 12", na=False)
        ]
    )

    total_college = len(
        students_unique[
            students_unique["Grade Level"]
            .astype(str)
            .str.contains("College", case=False, na=False)
        ]
    )

    return render_template(
        "reports.html",
        sports=sports,
        jhs_sports=jhs_sports,
        shs_sports=shs_sports,
        academic_years=academic_years,
        terms=terms,
        grade_levels=grade_levels,
        total_students=total_students,
        total_jhs=total_jhs,
        total_shs=total_shs,
        total_college=total_college
    )

@app.route("/edit_student/<student_id>", methods=["GET", "POST"])
def edit_student(student_id):

    df = load_data()
    visible_df = filter_data_by_role(df)

    student_records = visible_df[
        visible_df["Student ID"].astype(str) == str(student_id)
    ]

    if student_records.empty:
        return "Student not found"

    student = student_records.iloc[0].to_dict()

    if request.method == "POST":

        full_name = request.form.get("full_name", "")
        grade_level = request.form.get("grade_level", "")
        section = request.form.get("section", "")
        strand = request.form.get("strand", "")
        year_level = request.form.get("year_level", "")
        course_program = request.form.get("course_program", "")
        college = request.form.get("college", "")
        sport = request.form.get("sport", "")

        mask = df["Student ID"].astype(str) == str(student_id)

        df.loc[mask, "Full Name"] = full_name
        df.loc[mask, "Grade Level"] = grade_level
        df.loc[mask, "Section"] = section
        df.loc[mask, "Strand"] = strand
        df.loc[mask, "Year Level"] = year_level
        df.loc[mask, "Course / Program"] = course_program
        df.loc[mask, "College"] = college
        df.loc[mask, "Sports Events"] = sport
        df.loc[mask, "Sport"] = sport

        save_data(df)

        return redirect("/student_list")

    basic_ed_sports = get_sports_by_group("basic_ed")
    college_sports = get_sports_by_group("college")

    return render_template(
        "edit_student.html",
        student=student,
        basic_ed_sports=basic_ed_sports,
        college_sports=college_sports,
        show_value=show_value
    )

@app.route("/add_student", methods=["GET", "POST"])
def add_student():
    df = load_data()
    role = session.get("role")

    if request.method == "POST":
        student_id = request.form.get("student_id", "")
        full_name = request.form.get("full_name", "")
        grade_level = request.form.get("grade_level", "")
        section = request.form.get("section", "")
        strand = request.form.get("strand", "")
        year_level = request.form.get("year_level", "")
        course_program = request.form.get("course_program", "")
        college_department = request.form.get("college_department", "")
        sport = request.form.get("sport", "")
        academic_year = request.form.get("academic_year", "")

        if role == "admin_college":
            grade_level = "College"

        new_student = {
            "Student ID": student_id,
            "Full Name": full_name,
            "Grade Level": grade_level,
            "Section": section,
            "Strand": strand,
            "Year Level": year_level,
            "Course / Program": course_program,
            "College": college_department,
            "Sports Events": sport,
            "Sport": sport,
            "Academic Year": academic_year,
            "Term": "",
            "Subject_Display": "",
            "Subject": "",
            "Q1": "",
            "Q2": "",
            "Q3": "",
            "Q4": "",
            "Midterm": "",
            "Final": "",
            "Final Term Grade": "",
            "Remarks": ""
        }

        df = pd.concat([df, pd.DataFrame([new_student])], ignore_index=True)
        save_data(df)

        return redirect("/student_list")

    basic_ed_sports = get_sports_by_group("basic_ed")
    college_sports = get_sports_by_group("college")
    programs = get_programs_for_dropdown()

    return render_template(
        "add_student.html",
        basic_ed_sports=basic_ed_sports,
        college_sports=college_sports,
        programs=programs
    )


@app.route("/promote_students", methods=["GET", "POST"])
def promote_students():

    if session.get("role") != "super_admin":
        return redirect("/student_list")

    if request.method == "POST":

        old_academic_year = request.form.get("old_academic_year")
        new_academic_year = request.form.get("new_academic_year")

        df = load_data()

        students_only = df.drop_duplicates(
            subset=["Student ID"]
        ).copy()

        promoted_students = []

        for _, student in students_only.iterrows():

            if str(student.get("Academic Year", "")) != old_academic_year:
                continue

            current_grade = str(student.get("Grade Level", ""))
            current_year = str(student.get("Year Level", ""))

            new_grade, new_year = promote_grade_level(
                current_grade,
                current_year
            )

            if new_grade == "Graduated":
                continue

            new_student = student.copy()

            new_student["Academic Year"] = new_academic_year
            new_student["Grade Level"] = new_grade
            new_student["Year Level"] = new_year

            promoted_students.append(new_student)

        if promoted_students:

            new_df = pd.DataFrame(promoted_students)

            df = pd.concat(
                [df, new_df],
                ignore_index=True
            )

            save_data(df)

        return redirect("/student_list")

    return render_template("promote_students.html")

@app.route("/manage_sports", methods=["GET", "POST"])
def manage_sports():

    if session.get("role") != "super_admin":
        return redirect("/")

    with engine.begin() as conn:

        if request.method == "POST":

            sport_name = request.form["sport_name"]
            level_group = request.form["level_group"]

            conn.exec_driver_sql(
                """
                INSERT INTO sports (sport_name, level_group)
                VALUES (%s, %s)
                """,
                (sport_name, level_group)
            )

            return redirect("/manage_sports")

        sports = conn.exec_driver_sql(
            """
            SELECT id, sport_name, level_group
            FROM sports
            ORDER BY level_group, sport_name
            """
        ).fetchall()

    return render_template(
        "manage_sports.html",
        sports=sports
    )

@app.route("/delete_sport/<int:sport_id>")
def delete_sport(sport_id):

    if session.get("role") != "super_admin":
        return redirect("/")

    with engine.begin() as conn:
        conn.exec_driver_sql(
            "DELETE FROM sports WHERE id = %s",
            (sport_id,)
        )

    return redirect("/manage_sports")

def init_colleges_courses_tables():

    with engine.begin() as conn:

        conn.exec_driver_sql("""
            CREATE TABLE IF NOT EXISTS colleges (
                id SERIAL PRIMARY KEY,
                college_name TEXT UNIQUE NOT NULL
            )
        """)

        conn.exec_driver_sql("""
            CREATE TABLE IF NOT EXISTS courses (
                id SERIAL PRIMARY KEY,
                course_name TEXT UNIQUE NOT NULL,
                college_id INTEGER REFERENCES colleges(id)
            )
        """)

def init_departments_programs_tables():

    with engine.begin() as conn:
        conn.exec_driver_sql("""
            CREATE TABLE IF NOT EXISTS departments (
                id SERIAL PRIMARY KEY,
                department_name TEXT UNIQUE NOT NULL
            )
        """)

        conn.exec_driver_sql("""
            CREATE TABLE IF NOT EXISTS programs (
                id SERIAL PRIMARY KEY,
                program_name TEXT UNIQUE NOT NULL,
                department_id INTEGER REFERENCES departments(id) ON DELETE CASCADE
            )
        """)


def get_departments():
    with engine.begin() as conn:
        rows = conn.exec_driver_sql("""
            SELECT id, department_name
            FROM departments
            ORDER BY department_name
        """).fetchall()

    return rows


def get_programs():
    with engine.begin() as conn:
        rows = conn.exec_driver_sql("""
            SELECT 
                programs.id,
                programs.program_name,
                departments.department_name
            FROM programs
            JOIN departments ON programs.department_id = departments.id
            ORDER BY departments.department_name, programs.program_name
        """).fetchall()

    return rows


def get_programs_for_dropdown():
    with engine.begin() as conn:
        rows = conn.exec_driver_sql("""
            SELECT 
                programs.program_name,
                departments.department_name
            FROM programs
            JOIN departments ON programs.department_id = departments.id
            ORDER BY programs.program_name
        """).fetchall()

    return [
        {
            "program_name": row[0],
            "department_name": row[1]
        }
        for row in rows
    ]


@app.route("/manage_departments", methods=["GET", "POST"])
def manage_departments():

    if session.get("role") != "super_admin":
        return redirect("/")

    if request.method == "POST":
        department_name = request.form.get("department_name", "").strip()

        if department_name:
            try:
                with engine.begin() as conn:
                    conn.exec_driver_sql(
                        """
                        INSERT INTO departments (department_name)
                        VALUES (%s)
                        """,
                        (department_name,)
                    )
            except Exception as e:
                print("ADD DEPARTMENT ERROR:", e)

        return redirect("/manage_departments")

    departments = get_departments()

    return render_template(
        "manage_departments.html",
        departments=departments
    )


@app.route("/delete_department/<int:department_id>")
def delete_department(department_id):

    if session.get("role") != "super_admin":
        return redirect("/")

    with engine.begin() as conn:
        conn.exec_driver_sql(
            "DELETE FROM departments WHERE id = %s",
            (department_id,)
        )

    return redirect("/manage_departments")


@app.route("/manage_programs", methods=["GET", "POST"])
def manage_programs():

    if session.get("role") != "super_admin":
        return redirect("/")

    if request.method == "POST":
        program_name = request.form.get("program_name", "").strip()
        department_id = request.form.get("department_id", "").strip()

        if program_name and department_id:
            try:
                with engine.begin() as conn:
                    conn.exec_driver_sql(
                        """
                        INSERT INTO programs (program_name, department_id)
                        VALUES (%s, %s)
                        """,
                        (program_name, department_id)
                    )
            except Exception as e:
                print("ADD PROGRAM ERROR:", e)

        return redirect("/manage_programs")

    departments = get_departments()
    programs = get_programs()

    return render_template(
        "manage_programs.html",
        departments=departments,
        programs=programs
    )


@app.route("/delete_program/<int:program_id>")
def delete_program(program_id):

    if session.get("role") != "super_admin":
        return redirect("/")

    with engine.begin() as conn:
        conn.exec_driver_sql(
            "DELETE FROM programs WHERE id = %s",
            (program_id,)
        )

    return redirect("/manage_programs")


init_users_table()
init_sports_table()
init_colleges_courses_tables()
init_departments_programs_tables()

@app.route("/print_students")
def print_students():

    df = load_data()
    df = filter_data_by_role(df)

    grade_level = request.args.get("grade_level", "")
    sport = request.args.get("sport", "")

    if grade_level:
        df = df[
            df["Grade Level"].astype(str) == grade_level
        ]

    if sport:
        df = df[
            df["Sports Events"].astype(str) == sport
        ]

    students = (
        df[
            [
                "Student ID",
                "Full Name",
                "Grade Level",
                "Sports Events"
            ]
        ]
        .drop_duplicates()
        .sort_values("Full Name")
    )

    return render_template(
        "print_students.html",
        students=students.to_dict("records"),
        grade_level=grade_level,
        sport=sport
    )

@app.route("/failed_students")
def failed_students():
    df = load_data()
    df = filter_data_by_role(df)

    if df.empty:
        return render_template(
            "failed_students.html",
            grouped_records={},
            show_value=show_value
        )

    df["Term"] = df["Term"].apply(normalize_term)

    failed_records = []

    for _, row in df.iterrows():
        grade_level = str(row.get("Grade Level", ""))
        student_id = str(row.get("Student ID", "")).strip()

        if student_id == "":
            continue

        subject = get_subject(row)
        if subject.strip() == "":
            continue

        is_failed = False
        period = ""
        display_grade = ""
        remarks = ""

        if is_college(grade_level):
            midterm = str(row.get("Midterm", "")).strip().upper()
            final = str(row.get("Final", "")).strip().upper()

            if final:
                period = "Final"
                display_grade = final
            else:
                period = "Midterm"
                display_grade = midterm

            remarks = compute_college_remarks(display_grade)

            if remarks in ["FAILED", "REPEAT", "INCOMPLETE", "DROPPED"]:
                is_failed = True

        else:
            grade = row.get("Final Term Grade")

            try:
                grade_num = float(grade)
                display_grade = int(round(grade_num))
                period = "Average"

                if grade_num < 75:
                    is_failed = True
                    remarks = "FAILED"

            except:
                pass

        if is_failed:
            failed_records.append({
                "student_id": student_id,
                "full_name": row.get("Full Name", ""),
                "grade_level": row.get("Grade Level", ""),
                "sport": row.get("Sports Events", ""),
                "academic_year": row.get("Academic Year", ""),
                "term": normalize_term(row.get("Term", "")),
                "period": period,
                "subject": subject,
                "grade": display_grade,
                "remarks": remarks
            })

    failed_records = sorted(
        failed_records,
        key=lambda x: (
            str(x["full_name"]).lower(),
            str(x["academic_year"]),
            str(x["term"]),
            str(x["subject"]).lower()
        )
    )

    grouped_records = {}

    for record in failed_records:
        student_id = record["student_id"]

        if student_id not in grouped_records:
            grouped_records[student_id] = {
                "student_info": record,
                "subjects": []
            }

        grouped_records[student_id]["subjects"].append({
            "term": record["term"],
            "period": record["period"],
            "subject": record["subject"],
            "grade": record["grade"],
            "remarks": record["remarks"]
        })

    return render_template(
        "failed_students.html",
        grouped_records=grouped_records,
        show_value=show_value
    )

@app.route("/delete_grade/<int:row_index>/<student_id>")
def delete_grade(row_index, student_id):

    if session.get("role") not in ["super_admin", "admin_jhs_shs", "admin_college"]:
        return redirect("/student_list")

    df = load_data()

    if row_index in df.index:
        df = df.drop(index=row_index)
        df.reset_index(drop=True, inplace=True)
        save_data(df)

    return redirect(f"/edit_grades/{student_id}")



if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5050, debug=True)