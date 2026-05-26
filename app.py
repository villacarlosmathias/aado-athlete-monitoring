from flask import Flask, render_template, request, redirect, session, make_response
from sqlalchemy import create_engine
import pandas as pd
from sqlalchemy import create_engine
import os
import sqlite3
import os
import shutil
from datetime import datetime
from io import BytesIO

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
    "sqlite:///database.db"
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

        result = conn.exec_driver_sql(
            "SELECT COUNT(*) FROM users WHERE role = 'super_admin'"
        ).scalar()

        if result == 0:
            conn.exec_driver_sql("""
                INSERT INTO users (username, password, role, status)
                VALUES ('superadmin', 'superadmin123', 'super_admin', 'approved')
            """)

init_users_table()


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

    if term in ["1ST", "1ST TERM", "FIRST"]:
        return "1st"
    if term in ["2ND", "2ND TERM", "SECOND"]:
        return "2nd"
    if term in ["3RD", "3RD TERM", "THIRD"]:
        return "3rd"
    if term in ["4TH", "4TH TERM", "FOURTH"]:
        return "4th"

    return term.title()


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


def compute_college_remarks(final_grade):
    final_grade = str(final_grade).strip().upper()

    if final_grade == "" or final_grade == "NAN":
        return ""

    if final_grade == "R":
        return "Repeat"

    return "Passed"

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


@app.route("/login", methods=["GET", "POST"])
def login():
    error = ""

    if request.method == "POST":

        username = request.form.get("username")
        password = request.form.get("password")

        with engine.begin() as conn:
            user = conn.exec_driver_sql(
                """
                SELECT username, password, role, status
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

            return redirect("/")

    return render_template("login.html", error=error)


@app.route("/register", methods=["GET", "POST"])
def register():

    if request.method == "POST":

        username = request.form["username"]
        password = request.form["password"]
        role = request.form["role"]

        users = load_users()

        if username in users:
            return render_template(
                "register.html",
                error="Username already exists"
            )

        users[username] = {
            "password": password,
            "role": role,
            "approved": False
        }

        save_users(users)

        return redirect("/login")

    return render_template("register.html")


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


@app.route("/logout")
def logout():
    session.clear()
    return redirect("/login")


@app.before_request
def protect_pages():
    allowed_routes = ["login", "static"]

    if request.endpoint in allowed_routes:
        return

    if not session.get("logged_in"):
        return redirect("/login")

    if session.get("role") == "assistant":
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

    if df.empty:
        total_students = 0
        passed_students = 0
        failed_students = 0
        total_sports = 0
    else:
        total_students = df["Student ID"].astype(str).nunique()

        failed_ids = df[
            pd.to_numeric(df["Final Term Grade"], errors="coerce") < 75
        ]["Student ID"].astype(str).unique()

        failed_students = len(failed_ids)
        passed_students = total_students - failed_students
        total_sports = df["Sports Events"].dropna().astype(str).nunique()

    return render_template(
        "dashboard.html",
        total_students=total_students,
        passed_students=passed_students,
        failed_students=failed_students,
        total_sports=total_sports
    )


@app.route("/student_list")
def student_list():
    df = load_data()

    if df.empty:
        return render_template(
            "student_list.html",
            students=pd.DataFrame(),
            sports=[],
            grade_levels=[],
            show_value=show_value
        )

    sports = sorted(df["Sport"].dropna().astype(str).unique())
    grade_levels = sorted(df["Grade Level"].dropna().astype(str).unique())

    filtered_df = df.copy()

    sport_filter = request.args.get("sport")
    grade_filter = request.args.get("grade_level")
    search = request.args.get("search")

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

    students = filtered_df.drop_duplicates(subset=["Student ID"])
    students = students.sort_values(by="Full Name")

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

        academic_year = request.form.get("academic_year")

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

            subject_section = (
                subject_sections[i]
                if i < len(subject_sections)
                else ""
            )

            row = {
                "Student ID": student["Student ID"],
                "Full Name": student["Full Name"],
                "Grade Level": student["Grade Level"],

                "Section": student.get("Section", ""),
                "Strand": student.get("Strand", ""),

                "Year Level": student.get("Year Level", ""),
                "Course / Program": student.get("Course / Program", ""),
                "College": student.get("College", ""),

                "Sports Events": student.get("Sports Events", student.get("Sport", "")),
                "Sport": student.get("Sport", student.get("Sports Events", "")),

                "Academic Year": academic_year,

                "Term": normalize_term(terms[i]),

                "Subject_Display": subject,
                "Subject": subject,

                "Subject Section": subject_section
            }

            # =========================
            # COLLEGE
            # =========================

            if student_level == "COLLEGE":

                midterm = (
                    midterms[i]
                    if i < len(midterms)
                    else ""
                )

                final = (
                    finals[i]
                    if i < len(finals)
                    else ""
                )

                row["Midterm"] = midterm
                row["Final"] = final

                row["Q1"] = ""
                row["Q2"] = ""
                row["Q3"] = ""
                row["Q4"] = ""

                row["Final Term Grade"] = final

                row["Remarks"] = compute_college_remarks(final)

            # =========================
            # SHS
            # =========================

            elif student_level == "SHS":

                midterm = (
                    midterms[i]
                    if i < len(midterms)
                    else ""
                )

                final = (
                    finals[i]
                    if i < len(finals)
                    else ""
                )

                row["Midterm"] = midterm
                row["Final"] = final

                row["Q1"] = ""
                row["Q2"] = ""
                row["Q3"] = ""
                row["Q4"] = ""

                avg, remarks = compute_average([
                    midterm,
                    final
                ])

                row["Final Term Grade"] = avg

                row["Remarks"] = (
                    ""
                    if remarks == "NO GRADE"
                    else remarks
                )

            # =========================
            # JHS
            # =========================

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

                avg, remarks = compute_average([
                    q1,
                    q2,
                    q3,
                    q4
                ])

                row["Final Term Grade"] = avg

                row["Remarks"] = (
                    ""
                    if remarks == "NO GRADE"
                    else remarks
                )

            df = pd.concat(
                [df, pd.DataFrame([row])],
                ignore_index=True
            )

        save_data(df)

        return redirect(
            f"/edit_grades/{student_id}"
        )

    return render_template(
        "add_grade.html",
        student=student,
        student_level=student_level,
        show_value=show_value
    )

@app.route("/edit_grades/<student_id>", methods=["GET", "POST"])
def edit_grades(student_id):
    df = load_data()

    student_records = df[df["Student ID"].astype(str) == str(student_id)]

    if student_records.empty:
        return "No records found"

    student = student_records.iloc[0].to_dict()
    grade_level = str(student.get("Grade Level", ""))

    student_level = "SHS" if is_shs(grade_level) else "JHS"

    if request.method == "POST":
        row_indexes = request.form.getlist("row_index[]")

        for row_index in row_indexes:
            idx = int(row_index)

            if student_level == "SHS":
                midterm = request.form.get(f"midterm_{idx}")
                final = request.form.get(f"final_{idx}")

                df.loc[idx, "Midterm"] = midterm
                df.loc[idx, "Final"] = final

                avg, remarks = compute_average([midterm, final])
                df.loc[idx, "Final Term Grade"] = avg
                df.loc[idx, "Remarks"] = "" if remarks == "NO GRADE" else remarks

            else:
                q1 = request.form.get(f"q1_{idx}")
                q2 = request.form.get(f"q2_{idx}")
                q3 = request.form.get(f"q3_{idx}")
                q4 = request.form.get(f"q4_{idx}")

                df.loc[idx, "Q1"] = q1
                df.loc[idx, "Q2"] = q2
                df.loc[idx, "Q3"] = q3
                df.loc[idx, "Q4"] = q4

                avg, remarks = compute_average([q1, q2, q3, q4])
                df.loc[idx, "Final Term Grade"] = avg
                df.loc[idx, "Remarks"] = "" if remarks == "NO GRADE" else remarks

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

    if df.empty:
        return render_template(
            "grades.html",
            matched_students=pd.DataFrame(),
            grouped_records={},
            show_value=show_value,
            sports=[],
            academic_years=[],
            terms=[],
            grade_levels=[]
        )

    df["Term"] = df["Term"].apply(normalize_term)

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

            row_dict["Type"] = "SHS" if is_shs(grade_level) else "JHS"
            row_dict["Subject_Display"] = get_subject(row_dict)

            term = normalize_term(row_dict.get("Term", ""))

            group_title = (
                f'{row_dict.get("Full Name", "")} | '
                f'{row_dict.get("Grade Level", "")} | '
                f'AY {row_dict.get("Academic Year", "")} - '
                f'{term}'
            )

            if group_title not in grouped_records:
                grouped_records[group_title] = []

            grouped_records[group_title].append(row_dict)

    sports = sorted(df["Sports Events"].dropna().astype(str).unique())
    academic_years = sorted(df["Academic Year"].dropna().astype(str).unique())
    term_values = df["Term"].dropna().astype(str).apply(normalize_term).unique()

    term_order = ["1st", "2nd", "3rd", "4th"]

    terms = [
        term for term in term_order
        if term in term_values
    ]
    grade_levels = sorted(df["Grade Level"].dropna().astype(str).unique())

    return render_template(
        "grades.html",
        matched_students=matched_students,
        grouped_records=grouped_records,
        show_value=show_value,
        sports=sports,
        academic_years=academic_years,
        terms=terms,
        grade_levels=grade_levels
    )


@app.route("/delete_grade/<int:row_index>/<student_id>")
def delete_grade(row_index, student_id):
    df = load_data()

    df = df.drop(index=row_index)
    df.reset_index(drop=True, inplace=True)

    save_data(df)

    return redirect(f"/edit_grades/{student_id}")


@app.route("/export_pdf")
def export_pdf():
    df = load_data()

    if df.empty:
        return "No data available"

    df["Term"] = df["Term"].apply(normalize_term)

    level = request.args.get("level", "ALL").upper()
    sport = request.args.get("sport", "")
    term = request.args.get("term", "")
    academic_year = request.args.get("academic_year", "")
    grade_level = request.args.get("grade_level", "")

    if level == "JHS":
        df = df[~df["Grade Level"].astype(str).str.contains("11|12", na=False)]
        report_type = "JHS Assessment Report"
        pdf_columns = "JHS"

    elif level == "SHS":
        df = df[df["Grade Level"].astype(str).str.contains("11|12", na=False)]
        report_type = "SHS Assessment Report"
        pdf_columns = "SHS"

    else:
        report_type = "All Students Assessment Report"
        pdf_columns = "ALL"

    if sport:
        df = df[df["Sports Events"].astype(str) == sport]

    if term:
        df = df[df["Term"].astype(str) == normalize_term(term)]

    if academic_year:
        df = df[df["Academic Year"].astype(str) == academic_year]

    if grade_level:
        df = df[df["Grade Level"].astype(str) == grade_level]

    df["Subject_Display"] = df.apply(lambda row: get_subject(row), axis=1)

    df = df.sort_values(
        by=["Full Name", "Academic Year", "Term", "Subject_Display"],
        na_position="last"
    )

    buffer = BytesIO()

    doc = SimpleDocTemplate(
        buffer,
        pagesize=landscape(legal),
        rightMargin=10,
        leftMargin=10,
        topMargin=15,
        bottomMargin=15
    )

    styles = getSampleStyleSheet()

    title_style = ParagraphStyle(
        "TitleStyle",
        parent=styles["Title"],
        fontSize=20,
        leading=24,
        alignment=TA_CENTER,
        textColor=colors.black,
        spaceAfter=4
    )

    subtitle_style = ParagraphStyle(
        "SubtitleStyle",
        parent=styles["Heading2"],
        fontSize=16,
        leading=18,
        alignment=TA_CENTER,
        textColor=colors.black,
        spaceAfter=10
    )

    small_style = ParagraphStyle(
        "SmallStyle",
        parent=styles["Normal"],
        fontSize=6.5,
        leading=7.5,
        alignment=TA_CENTER
    )

    subject_style = ParagraphStyle(
        "SubjectStyle",
        parent=styles["Normal"],
        fontSize=6.5,
        leading=7.5,
        alignment=TA_LEFT
    )

    elements = []

    logo_path = "static/nu_logo.png"

    if os.path.exists(logo_path):
        logo = Image(
            logo_path,
            width=420,
            height=95
        )
        elements.append(logo)

    elements.append(Spacer(1, 10))

    display_term = normalize_term(term) if term else "All Terms"

    elements.append(
        Paragraph(
            f"{display_term.upper()} {report_type.upper()}",
            subtitle_style
        )
    )

    elements.append(
        Paragraph(
            f"AY {academic_year if academic_year else 'All Academic Years'}",
            subtitle_style
        )
    )

    elements.append(Spacer(1, 8))

    if pdf_columns == "SHS":
        headers = [
            "Fullname",
            "Student ID No.",
            "Grade",
            "Sports / Events",
            "AY",
            "Term",
            "Subject",
            "Midterm",
            "Final",
            "Final Term Grade",
            "Status"
        ]
        col_widths = [95, 75, 45, 85, 60, 40, 310, 55, 55, 75, 65]

    elif pdf_columns == "JHS":
        headers = [
            "Fullname",
            "Student ID No.",
            "Grade",
            "Sports / Events",
            "AY",
            "Term",
            "Subject",
            "Q1",
            "Q2",
            "Q3",
            "Q4",
            "Final Term Grade",
            "Status"
        ]
        col_widths = [90, 70, 45, 80, 55, 40, 285, 40, 40, 40, 40, 75, 65]

    else:
        headers = [
            "Fullname",
            "Student ID No.",
            "Grade",
            "Sports / Events",
            "AY",
            "Term",
            "Subject",
            "Q1",
            "Q2",
            "Q3",
            "Q4",
            "Midterm",
            "Final",
            "Final Term Grade",
            "Status"
        ]
        col_widths = [80, 65, 40, 70, 50, 35, 230, 35, 35, 35, 35, 45, 45, 65, 60]

    table_data = [headers]

    previous_student_id = None

    for _, row in df.iterrows():
        subject = get_subject(row)
        grade_level_value = str(row.get("Grade Level", ""))
        term_value = normalize_term(row.get("Term", ""))

        current_student_id = str(row.get("Student ID", ""))

        if current_student_id != previous_student_id:
            display_name = str(show_value(row.get("Full Name")))
            display_student_id = str(show_value(row.get("Student ID")))
            display_grade = str(show_value(row.get("Grade Level")))
            display_sport = str(show_value(row.get("Sports Events")))
            previous_student_id = current_student_id
        else:
            display_name = ""
            display_student_id = ""
            display_grade = ""
            display_sport = ""

        q1 = number_or_blank(row.get("Q1"))
        q2 = number_or_blank(row.get("Q2"))
        q3 = number_or_blank(row.get("Q3"))
        q4 = number_or_blank(row.get("Q4"))
        midterm = number_or_blank(row.get("Midterm"))
        final = number_or_blank(row.get("Final"))

        if is_shs(grade_level_value):
            average, remarks = compute_average([midterm, final])
        else:
            average, remarks = compute_average([q1, q2, q3, q4])

        average_display = average if average != "" else ""
        remarks_display = remarks

        base = [
            Paragraph(display_name, small_style),
            display_student_id,
            display_grade,
            Paragraph(display_sport, small_style),
            str(show_value(row.get("Academic Year"))),
            term_value,
            Paragraph(subject, subject_style),
        ]

        if pdf_columns == "SHS":
            row_data = base + [
                midterm,
                final,
                average_display,
                remarks_display
            ]

        elif pdf_columns == "JHS":
            row_data = base + [
                q1,
                q2,
                q3,
                q4,
                average_display,
                remarks_display
            ]

        else:
            row_data = base + [
                q1,
                q2,
                q3,
                q4,
                midterm,
                final,
                average_display,
                remarks_display
            ]

        table_data.append(row_data)

    table = Table(
        table_data,
        repeatRows=1,
        colWidths=col_widths
    )

    table_style = TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.black),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 5.8),

        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("ALIGN", (0, 1), (0, -1), "LEFT"),
        ("ALIGN", (3, 1), (3, -1), "LEFT"),
        ("ALIGN", (6, 1), (6, -1), "LEFT"),

        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("GRID", (0, 0), (-1, -1), 0.45, colors.black),

        ("TOPPADDING", (0, 0), (-1, 0), 4),
        ("BOTTOMPADDING", (0, 0), (-1, 0), 4),
        ("TOPPADDING", (0, 1), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 1), (-1, -1), 3),
    ])

    remarks_col = len(headers) - 1

    for row_index in range(1, len(table_data)):
        remark = str(table_data[row_index][remarks_col]).upper().strip()

        if remark in ["PASSED", "PASS"]:
            table_style.add("TEXTCOLOR", (remarks_col, row_index), (remarks_col, row_index), colors.green)
            table_style.add("FONTNAME", (remarks_col, row_index), (remarks_col, row_index), "Helvetica-Bold")

        elif remark == "FAILED":
            table_style.add("TEXTCOLOR", (remarks_col, row_index), (remarks_col, row_index), colors.red)
            table_style.add("FONTNAME", (remarks_col, row_index), (remarks_col, row_index), "Helvetica-Bold")

        elif remark == "NO GRADE":
            table_style.add("TEXTCOLOR", (remarks_col, row_index), (remarks_col, row_index), colors.orange)
            table_style.add("FONTNAME", (remarks_col, row_index), (remarks_col, row_index), "Helvetica-Bold")

    table.setStyle(table_style)

    elements.append(table)

    elements.append(Spacer(1, 40))

    signature_data = [[
    Paragraph(
        "<b>Prepared By:</b><br/><br/><br/><br/>"
        "______________________________<br/>"
        "Mathias Villacarlos Jr.<br/>"
        "AADO Associate",
        styles["Normal"]
    ),

    Paragraph(
        "<b>Reviewed By:</b><br/><br/><br/><br/>"
        "______________________________<br/>"
        "Ms. Maria Ester V. Suarez<br/>"
        "Assistant Director, AADO",
        styles["Normal"]
    )
]]

    signature_table = Table(
    signature_data,
    colWidths=[420, 420]
)

    signature_table.setStyle(TableStyle([
    ("VALIGN", (0,0), (-1,-1), "TOP"),
    ("ALIGN", (0,0), (0,0), "LEFT"),
    ("ALIGN", (1,0), (1,0), "RIGHT"),
]))

    elements.append(signature_table)

    doc.build(elements)

    pdf = buffer.getvalue()
    buffer.close()

    response = make_response(pdf)
    response.headers["Content-Type"] = "application/pdf"
    response.headers["Content-Disposition"] = "attachment; filename=grades_report.pdf"

    return response

@app.route("/intervention_report")
def intervention_report():
    df = load_data()

    report_type = request.args.get("type", "remedial")

    level = request.args.get("level", "ALL").upper()
    sport = request.args.get("sport", "")
    term = request.args.get("term", "")
    academic_year = request.args.get("academic_year", "")
    grade_level_filter = request.args.get("grade_level", "")

    rows = []

    df["Term"] = df["Term"].apply(normalize_term)

    if level == "JHS":
        df = df[
            ~df["Grade Level"].astype(str).str.contains("11|12", na=False)
        ]

    elif level == "SHS":
        df = df[
            df["Grade Level"].astype(str).str.contains("11|12", na=False)
        ]

    if sport:
        df = df[
            df["Sports Events"].astype(str) == sport
        ]

    if term:
        df = df[
            df["Term"].astype(str) == normalize_term(term)
        ]

    if academic_year:
        df = df[
            df["Academic Year"].astype(str) == academic_year
        ]

    if grade_level_filter:
        df = df[
            df["Grade Level"].astype(str) == grade_level_filter
        ]

    for _, row in df.iterrows():

        grade_level = str(row.get("Grade Level", ""))

        q1 = number_or_blank(row.get("Q1"))
        q2 = number_or_blank(row.get("Q2"))
        q3 = number_or_blank(row.get("Q3"))
        q4 = number_or_blank(row.get("Q4"))

        midterm = number_or_blank(row.get("Midterm"))
        final = number_or_blank(row.get("Final"))

        if is_shs(grade_level):
            average, _ = compute_average([midterm, final])
        else:
            average, _ = compute_average([q1, q2, q3, q4])

        if average == "":
            continue

        average = int(average)

        if report_type == "remedial":
            if not (71 <= average <= 74):
                continue

        elif report_type == "load_revision":
            if not (average <= 70):
                continue

        rows.append([
            str(show_value(row.get("Student ID"))),
            str(show_value(row.get("Full Name"))),
            str(show_value(row.get("Grade Level"))),
            str(show_value(row.get("Sports Events"))),
            str(show_value(row.get("Academic Year"))),
            str(normalize_term(row.get("Term"))),
            str(get_subject(row)),
            str(average),
            "REMEDIAL" if report_type == "remedial" else "LOAD REVISION"
        ])

    title = (
        "Remedial Report"
        if report_type == "remedial"
        else "Load Revision Report"
    )

    filename = (
        "remedial_report.pdf"
        if report_type == "remedial"
        else "load_revision_report.pdf"
    )

    buffer = BytesIO()

    doc = SimpleDocTemplate(
        buffer,
        pagesize=landscape(legal),
        rightMargin=15,
        leftMargin=15,
        topMargin=20,
        bottomMargin=20
    )

    styles = getSampleStyleSheet()

    elements = []

    # =========================
    # LOGO
    # =========================

    logo_path = "static/nu_logo.png"

    if os.path.exists(logo_path):

        logo = Image(
            logo_path,
            width=420,
            height=95
        )

        elements.append(logo)

    elements.append(Spacer(1, 10))

    # =========================
    # TITLE
    # =========================

    elements.append(
        Paragraph(
            title,
            styles["Heading2"]
        )
    )

    elements.append(Spacer(1, 12))

    # =========================
    # TABLE
    # =========================

    data = [[
        "Student ID",
        "Full Name",
        "Grade Level",
        "Sport",
        "Academic Year",
        "Term",
        "Subject",
        "Final Grade",
        "Status"
    ]]

    data.extend(rows)

    table = Table(
        data,
        repeatRows=1,
        colWidths=[70, 140, 70, 100, 80, 60, 260, 80, 100]
    )

    table_style = TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.black),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 7),

        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("ALIGN", (1, 1), (1, -1), "LEFT"),
        ("ALIGN", (6, 1), (6, -1), "LEFT"),

        ("GRID", (0, 0), (-1, -1), 0.45, colors.black),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
    ])

    status_col = 8

    for row_index in range(1, len(data)):

        if report_type == "remedial":

            table_style.add(
                "TEXTCOLOR",
                (status_col, row_index),
                (status_col, row_index),
                colors.orange
            )

        else:

            table_style.add(
                "TEXTCOLOR",
                (status_col, row_index),
                (status_col, row_index),
                colors.red
            )

        table_style.add(
            "FONTNAME",
            (status_col, row_index),
            (status_col, row_index),
            "Helvetica-Bold"
        )

    table.setStyle(table_style)

    elements.append(table)

    # =========================
    # SIGNATURES
    # =========================

    elements.append(Spacer(1, 40))

    signature_data = [[

        Paragraph(
            "<b>Prepared By:</b><br/><br/><br/><br/>"
            "______________________________<br/>"
            "Mathias Villacarlos Jr.<br/>"
            "AADO Associate",
            styles["Normal"]
        ),

        Paragraph(
            "<b>Reviewed By:</b><br/><br/><br/><br/>"
            "______________________________<br/>"
            "Ms. Maria Ester V. Suarez<br/>"
            "Assistant Director, AADO",
            styles["Normal"]
        )

    ]]

    signature_table = Table(
        signature_data,
        colWidths=[420, 420]
    )

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

@app.route("/reports")
def reports():

    df = load_data()

    if df.empty:
        return render_template(
            "reports.html",
            sports=[],
            jhs_sports=[],
            shs_sports=[],
            academic_years=[],
            terms=[],
            grade_levels=[]
        )

    sports = sorted(
        df["Sports Events"]
        .dropna()
        .astype(str)
        .unique()
    )

    # JHS SPORTS
    jhs_df = df[
        ~df["Grade Level"]
        .astype(str)
        .str.contains("11|12", na=False)
    ]

    jhs_sports = sorted(
        jhs_df["Sports Events"]
        .dropna()
        .astype(str)
        .unique()
    )

    # SHS SPORTS
    shs_df = df[
        df["Grade Level"]
        .astype(str)
        .str.contains("11|12", na=False)
    ]

    shs_sports = sorted(
        shs_df["Sports Events"]
        .dropna()
        .astype(str)
        .unique()
    )

    academic_years = sorted(
        df["Academic Year"]
        .dropna()
        .astype(str)
        .unique()
    )

    term_values = df["Term"].dropna().astype(str).apply(normalize_term).unique()

    term_order = ["1st", "2nd", "3rd", "4th"]

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

    return render_template(
        "reports.html",
        sports=sports,
        jhs_sports=jhs_sports,
        shs_sports=shs_sports,
        academic_years=academic_years,
        terms=terms,
        grade_levels=grade_levels
    )

@app.route("/add_student", methods=["GET", "POST"])
def add_student():
    df = load_data()

    if request.method == "POST":
        student_id = request.form.get("student_id")
        full_name = request.form.get("full_name")
        grade_level = request.form.get("grade_level")
        section = request.form.get("section")
        strand = request.form.get("strand")
        year_level = request.form.get("year_level")
        course_program = request.form.get("course_program")
        college_department = request.form.get("college_department")
        sport = request.form.get("sport")
        academic_year = request.form.get("academic_year")

        new_student = {
            "Student ID": student_id,
            "Full Name": full_name,
            "Grade Level": grade_level,
            "Section": section,
            "Strand": strand,
            "Year Level": year_level,
            "Course / Program": course_program,
            "College": college_department,
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

    return render_template("add_student.html")

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

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5050, debug=True)