import os, enum, csv, io, time
from datetime import datetime
from functools import wraps
from flask import Flask, render_template, request, redirect, url_for, flash
from flask_migrate import Migrate
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from sqlalchemy import case
from dotenv import load_dotenv
import calendar
from datetime import date

load_dotenv()

app = Flask(__name__)
app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', 'glanaudit-secret-key-2026')
app.config['SQLALCHEMY_DATABASE_URI'] = os.getenv('DATABASE_URL')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# Photo Upload Configuration
UPLOAD_FOLDER = os.path.join('static', 'uploads', 'defects')
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'webp'}
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)


def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


db = SQLAlchemy(app)
migrate = Migrate(app, db)

login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'


# ==========================================
# DATABASE MODELS
# ==========================================

class UserRole(str, enum.Enum):
    DRIVER = 'Driver'
    MECHANIC = 'Mechanic'
    MANAGER = 'Manager'
    ADMIN = 'Admin'


class Company(db.Model):
    __tablename__ = 'companies'
    company_id = db.Column(db.Integer, primary_key=True)
    company_name = db.Column(db.String(100), nullable=False)
    rsa_licence_number = db.Column(db.String(20), nullable=False, unique=True)
    contact_email = db.Column(db.String(120), nullable=False, unique=True)
    phone_number = db.Column(db.String(20), nullable=False)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)


class Vehicle(db.Model):
    __tablename__ = 'vehicles'
    vehicle_id = db.Column(db.Integer, primary_key=True)
    company_id = db.Column(db.Integer, db.ForeignKey('companies.company_id'), nullable=False)
    registration_number = db.Column(db.String(20), nullable=False, unique=True)
    make_model = db.Column(db.String(100))
    vehicle_type = db.Column(db.String(20))
    pmi_interval_weeks = db.Column(db.Integer, default=13)
    current_status = db.Column(db.String(50), default='Active')
    next_cvrt_date = db.Column(db.Date)
    next_pmi_date = db.Column(db.Date)
    tax_expiry_date = db.Column(db.Date)
    insurance_expiry_date = db.Column(db.Date)
    tacho_calibration_date = db.Column(db.Date)


class User(UserMixin, db.Model):
    __tablename__ = 'users'
    user_id = db.Column(db.Integer, primary_key=True)
    company_id = db.Column(db.Integer, db.ForeignKey('companies.company_id'), nullable=True)
    full_name = db.Column(db.String(100), nullable=False)
    role = db.Column(db.Enum(UserRole, values_callable=lambda x: [e.value for e in x]), nullable=False, default=UserRole.DRIVER)
    email = db.Column(db.String(120), nullable=False, unique=True)
    pin_hash = db.Column(db.String(255), nullable=False)
    licence_expiry_date = db.Column(db.Date, nullable=True)
    cpc_expiry_date = db.Column(db.Date, nullable=True)
    is_active = db.Column(db.Boolean, default=True, nullable=False)

    def get_id(self):
        return str(self.user_id)

    def set_pin(self, raw_pin):
        self.pin_hash = generate_password_hash(raw_pin)

    def check_pin(self, raw_pin):
        return check_password_hash(self.pin_hash, raw_pin)


@login_manager.user_loader
def load_user(user_id):
    return db.session.get(User, int(user_id))


class WalkaroundLog(db.Model):
    __tablename__ = 'walkaround_logs'
    log_id = db.Column(db.Integer, primary_key=True)
    company_id = db.Column(db.Integer, db.ForeignKey('companies.company_id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('users.user_id'), nullable=False)
    vehicle_id = db.Column(db.Integer, db.ForeignKey('vehicles.vehicle_id'), nullable=False)
    trailer_id = db.Column(db.Integer, db.ForeignKey('vehicles.vehicle_id'), nullable=True)
    inspection_time = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    current_odometer = db.Column(db.Integer, nullable=False)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    is_roadworthy = db.Column(db.Boolean, nullable=False, default=True)
    check_data = db.Column(db.JSON, nullable=True)

    vehicle = db.relationship('Vehicle', foreign_keys=[vehicle_id], backref='walkaround_logs')
    driver = db.relationship('User', backref='walkaround_logs')


class VehicleHistory(db.Model):
    __tablename__ = 'vehicle_history'
    history_id = db.Column(db.Integer, primary_key=True)
    vehicle_id = db.Column(db.Integer, db.ForeignKey('vehicles.vehicle_id'), nullable=False)
    event_type = db.Column(db.String(50), nullable=False)
    event_date = db.Column(db.Date, nullable=False)
    odometer_reading = db.Column(db.Integer, nullable=False)
    document_url = db.Column(db.String(255), nullable=True)


class Defect(db.Model):
    __tablename__ = 'defects'
    defect_id = db.Column(db.Integer, primary_key=True)
    log_id = db.Column(db.Integer, db.ForeignKey('walkaround_logs.log_id'), nullable=False)
    vehicle_id = db.Column(db.Integer, db.ForeignKey('vehicles.vehicle_id'), nullable=False)
    category_id = db.Column(db.Integer, nullable=False)
    description = db.Column(db.Text, nullable=False)
    photo_url = db.Column(db.String(255), nullable=True)
    triage_decision = db.Column(db.Boolean, nullable=False, default=False)
    deferral_reason = db.Column(db.String(255), nullable=True)
    status = db.Column(db.String(50), default='Open')
    priority = db.Column(db.String(20), default='High', nullable=False)

    vehicle = db.relationship('Vehicle', backref='defects')
    walkaround = db.relationship('WalkaroundLog', backref='defects')


class RepairJob(db.Model):
    __tablename__ = 'repair_jobs'
    job_id = db.Column(db.Integer, primary_key=True)
    defect_id = db.Column(db.Integer, db.ForeignKey('defects.defect_id'), nullable=False)
    assigned_mechanic_id = db.Column(db.Integer, db.ForeignKey('users.user_id'), nullable=True)
    approving_manager_id = db.Column(db.Integer, db.ForeignKey('users.user_id'), nullable=True)
    parts_replaced = db.Column(db.Boolean, nullable=False, default=False)
    parts_cost = db.Column(db.Numeric(10, 2), nullable=True, default=0.00)
    repair_details = db.Column(db.Text, nullable=True)
    mechanic_signature = db.Column(db.String(255), nullable=True)
    final_manager_signature = db.Column(db.String(255), nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    assigned_mechanic = db.relationship('User', foreign_keys=[assigned_mechanic_id])
    defect = db.relationship('Defect', backref=db.backref('repair_job', uselist=False))


# ==========================================
# HELPER FUNCTIONS & DECORATORS
# ==========================================

def parse_date(date_str):
    if date_str:
        return datetime.strptime(date_str, '%Y-%m-%d').date()
    return None


def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        role_val = current_user.role.value if hasattr(current_user.role, 'value') else str(current_user.role)
        if not current_user.is_authenticated or role_val.upper() not in ['ADMIN']:
            flash('Access restricted to Super Admins.', 'error')
            return redirect(url_for('index'))
        return f(*args, **kwargs)

    return decorated_function


def manager_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        role_val = current_user.role.value if hasattr(current_user.role, 'value') else str(current_user.role)
        if not current_user.is_authenticated or role_val.upper() not in ['MANAGER', 'ADMIN']:
            flash('Access restricted to Fleet Managers.', 'error')
            return redirect(url_for('index'))
        if not current_user.company_id and role_val.upper() != 'ADMIN':
            flash('Your account is not assigned to a company.', 'error')
            return redirect(url_for('index'))
        return f(*args, **kwargs)

    return decorated_function


# ==========================================
# AUTH & SYSTEM ROUTES
# ==========================================

@app.route('/')
def index():
    if current_user.is_authenticated:
        role_val = (current_user.role.value if hasattr(current_user.role, 'value') else str(current_user.role)).upper()
        if role_val == 'MANAGER':
            return redirect(url_for('manager_dashboard'))
        elif role_val == 'MECHANIC':
            return redirect(url_for('mechanic_jobs'))

    vehicles = Vehicle.query.all()
    return render_template('index.html', vehicles=vehicles)


@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form.get('email', '').strip().lower()
        raw_pin = request.form.get('pin_code', '').strip()

        user = User.query.filter_by(email=email).first()
        if not user or not user.check_pin(raw_pin):
            flash('Invalid email or PIN.', 'error')
            return redirect(url_for('login'))

        if not user.is_active:
            flash('This account has been deactivated. Please contact your Fleet Manager.', 'error')
            return redirect(url_for('login'))

        login_user(user)
        flash('Logged in successfully!', 'success')
        return redirect(url_for('index'))

    return render_template('login.html')


@app.route('/logout')
@login_required
def logout():
    logout_user()
    flash('Logged out successfully.', 'info')
    return redirect(url_for('login'))


@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        email = request.form.get('email', '').strip().lower()
        raw_pin = request.form.get('pin_code', '').strip()

        user = User.query.filter_by(email=email).first()
        if user:
            flash('Email already exists.', 'error')
            return redirect(url_for('register'))

        role_str = request.form.get('role', 'Driver').upper()
        role_map = {'DRIVER': UserRole.DRIVER, 'MECHANIC': UserRole.MECHANIC, 'MANAGER': UserRole.MANAGER, 'ADMIN': UserRole.ADMIN}

        new_user = User(
            company_id=request.form.get('company_id') or None,
            full_name=request.form.get('full_name'),
            email=email,
            role=role_map.get(role_str, UserRole.DRIVER)
        )
        new_user.set_pin(raw_pin)

        db.session.add(new_user)
        db.session.commit()

        flash('Account created successfully!', 'success')
        return redirect(url_for('login'))

    return render_template('register.html', companies=Company.query.all())


# ==========================================
# ADMIN & MANAGER ROUTES
# ==========================================

@app.route('/admin/create_company', methods=['GET', 'POST'])
@login_required
@admin_required
def create_company():
    if request.method == 'POST':
        company_email = request.form.get('company_email', '').strip().lower()
        rsa_licence = request.form.get('rsa_licence_number', '').strip().upper()

        existing_company = Company.query.filter(
            (Company.rsa_licence_number == rsa_licence) | (Company.contact_email == company_email)
        ).first()

        if existing_company:
            flash('A company with this RSA licence or email already exists.', 'error')
            return redirect(url_for('create_company'))

        try:
            new_company = Company(
                company_name=request.form.get('company_name'),
                rsa_licence_number=rsa_licence,
                contact_email=company_email,
                phone_number=request.form.get('phone_number')
            )
            db.session.add(new_company)
            db.session.flush()

            manager_email = request.form.get('manager_email', '').strip().lower()
            raw_pin = request.form.get('manager_pin', '').strip()

            manager = User(
                company_id=new_company.company_id,
                full_name=request.form.get('manager_name'),
                email=manager_email,
                role=UserRole.MANAGER
            )
            manager.set_pin(raw_pin)

            db.session.add(manager)
            db.session.commit()

            flash(f'Successfully created company "{new_company.company_name}" and assigned Fleet Manager {manager.full_name}!', 'success')
            return redirect(url_for('index'))

        except Exception as e:
            db.session.rollback()
            flash(f'Error creating company: {str(e)}', 'error')
            return redirect(url_for('create_company'))

    return render_template('create_company.html')


@app.route('/manager/dashboard')
@login_required
@manager_required
def manager_dashboard():
    company = Company.query.get_or_404(current_user.company_id)
    vehicles = Vehicle.query.filter_by(company_id=company.company_id).all()

    staff = User.query.filter(
        User.company_id == company.company_id,
        User.role != UserRole.ADMIN
    ).all()

    driver_count = sum(1 for u in staff if (u.role.value if hasattr(u.role, 'value') else str(u.role)).upper() == 'DRIVER')
    mechanic_count = sum(1 for u in staff if (u.role.value if hasattr(u.role, 'value') else str(u.role)).upper() == 'MECHANIC')
    manager_count = sum(1 for u in staff if (u.role.value if hasattr(u.role, 'value') else str(u.role)).upper() == 'MANAGER')

    # Fetch active open/unresolved defects for the company fleet
    open_defects = (
        Defect.query.join(Vehicle)
        .filter(Vehicle.company_id == company.company_id, Defect.status != 'Resolved')
        .order_by(Defect.defect_id.desc())
        .all()
    )

    return render_template(
        'manager_dashboard.html',
        company=company,
        vehicles=vehicles,
        staff=staff,
        driver_count=driver_count,
        mechanic_count=mechanic_count,
        manager_count=manager_count,
        open_defects=open_defects
    )


@app.route('/manager/add_staff', methods=['GET', 'POST'])
@login_required
@manager_required
def manager_add_staff():
    if request.method == 'POST':
        role_str = request.form.get('role', 'Driver').upper()
        full_name = request.form.get('full_name', '').strip()
        email = request.form.get('email', '').strip().lower()
        pin_code = request.form.get('pin_code', '').strip()
        licence_expiry = parse_date(request.form.get('licence_expiry_date'))
        cpc_expiry = parse_date(request.form.get('cpc_expiry_date'))

        if User.query.filter_by(email=email).first():
            flash('An account with this email address already exists.', 'error')
            return redirect(url_for('manager_add_staff'))

        role_map = {
            'DRIVER': UserRole.DRIVER,
            'MECHANIC': UserRole.MECHANIC,
            'MANAGER': UserRole.MANAGER
        }
        assigned_role = role_map.get(role_str, UserRole.DRIVER)

        new_user = User(
            company_id=current_user.company_id,
            role=assigned_role,
            full_name=full_name,
            email=email,
            pin_hash=generate_password_hash(pin_code),
            licence_expiry_date=licence_expiry,
            cpc_expiry_date=cpc_expiry,
            is_active=True
        )

        db.session.add(new_user)
        db.session.commit()

        flash(f'Successfully created {role_str.capitalize()} account for {full_name}.', 'success')
        return redirect(url_for('manager_dashboard'))

    return render_template('add_staff.html')


@app.route('/manager/staff/<int:user_id>', methods=['GET', 'POST'])
@login_required
@manager_required
def manager_staff_detail(user_id):
    staff_member = User.query.filter_by(
        user_id=user_id,
        company_id=current_user.company_id
    ).first_or_404()

    if request.method == 'POST':
        role_str = request.form.get('role', 'Driver').upper()
        if role_str in UserRole.__members__:
            staff_member.role = UserRole[role_str]

        staff_member.full_name = request.form.get('full_name', staff_member.full_name).strip()
        staff_member.email = request.form.get('email', staff_member.email).strip().lower()

        new_pin = request.form.get('pin_code', '').strip()
        if new_pin:
            staff_member.set_pin(new_pin)

        staff_member.licence_expiry_date = parse_date(request.form.get('licence_expiry_date'))
        staff_member.cpc_expiry_date = parse_date(request.form.get('cpc_expiry_date'))
        staff_member.is_active = 'is_active' in request.form

        db.session.commit()
        flash(f'Updated profile and access rights for {staff_member.full_name}.', 'success')
        return redirect(url_for('manager_staff_detail', user_id=staff_member.user_id))

    user_walkarounds = (
        WalkaroundLog.query.filter_by(user_id=staff_member.user_id)
        .order_by(WalkaroundLog.log_id.desc())
        .all()
    )

    assigned_jobs = (
        RepairJob.query.filter_by(assigned_mechanic_id=staff_member.user_id)
        .order_by(RepairJob.job_id.desc())
        .all()
    )

    return render_template(
        'staff_detail.html',
        staff=staff_member,
        walkarounds=user_walkarounds,
        assigned_jobs=assigned_jobs
    )


@app.route('/manager/toggle_staff_status/<int:user_id>', methods=['POST'])
@login_required
@manager_required
def toggle_staff_status(user_id):
    if user_id == current_user.user_id:
        flash('You cannot deactivate your own manager account.', 'error')
        return redirect(url_for('manager_dashboard'))

    staff_member = User.query.filter_by(user_id=user_id, company_id=current_user.company_id).first_or_404()
    staff_member.is_active = not staff_member.is_active
    db.session.commit()

    status_str = "activated" if staff_member.is_active else "deactivated"
    flash(f'Account for {staff_member.full_name} has been {status_str}.', 'info')
    return redirect(url_for('manager_dashboard'))


@app.route('/manager/add_vehicle', methods=['GET', 'POST'])
@login_required
@manager_required
def manager_add_vehicle():
    if request.method == 'POST':
        reg_num = request.form.get('registration_number', '').strip().upper()
        make_model = request.form.get('make_model', '').strip()
        vehicle_type = request.form.get('vehicle_type')
        pmi_weeks = request.form.get('pmi_interval_weeks')
        current_status = request.form.get('current_status', 'Active').strip()

        cvrt_date = parse_date(request.form.get('next_cvrt_date'))
        pmi_date = parse_date(request.form.get('next_pmi_date'))
        tax_date = parse_date(request.form.get('tax_expiry_date'))
        insurance_date = parse_date(request.form.get('insurance_expiry_date'))
        tacho_date = parse_date(request.form.get('tacho_calibration_date'))

        existing = Vehicle.query.filter_by(company_id=current_user.company_id, registration_number=reg_num).first()
        if existing:
            flash(f'Vehicle {reg_num} is already registered.', 'error')
            return redirect(url_for('manager_add_vehicle'))

        new_vehicle = Vehicle(
            company_id=current_user.company_id,
            registration_number=reg_num,
            make_model=make_model,
            vehicle_type=vehicle_type,
            pmi_interval_weeks=int(pmi_weeks) if pmi_weeks else 13,
            current_status=current_status,
            next_cvrt_date=cvrt_date,
            next_pmi_date=pmi_date,
            tax_expiry_date=tax_date,
            insurance_expiry_date=insurance_date,
            tacho_calibration_date=tacho_date
        )

        db.session.add(new_vehicle)
        db.session.commit()

        flash(f'Successfully added vehicle {reg_num} ({current_status}).', 'success')
        return redirect(url_for('manager_dashboard'))

    return render_template('add_vehicle.html')


@app.route('/manager/bulk_import_vehicles', methods=['POST'])
@login_required
@manager_required
def bulk_import_vehicles():
    file = request.files.get('csv_file')
    if not file or not file.filename.endswith('.csv'):
        flash('Invalid file format. Please upload a valid CSV file.', 'error')
        return redirect(url_for('manager_add_vehicle'))

    stream = io.StringIO(file.stream.read().decode("UTF-8"), newline=None)
    csv_input = csv.DictReader(stream)

    imported_count = 0
    for row in csv_input:
        reg_num = row.get('registration_number', '').strip().upper()
        if not reg_num:
            continue

        existing = Vehicle.query.filter_by(company_id=current_user.company_id, registration_number=reg_num).first()
        if not existing:
            vehicle = Vehicle(
                company_id=current_user.company_id,
                registration_number=reg_num,
                make_model=row.get('make_model', '').strip(),
                vehicle_type=row.get('vehicle_type', 'HGV Rigid').strip(),
                pmi_interval_weeks=int(row.get('pmi_interval_weeks', 13)),
                current_status=row.get('current_status', 'Active').strip(),
                next_cvrt_date=parse_date(row.get('next_cvrt_date')),
                next_pmi_date=parse_date(row.get('next_pmi_date'))
            )
            db.session.add(vehicle)
            imported_count += 1

    db.session.commit()
    flash(f'Successfully imported {imported_count} fleet vehicles.', 'success')
    return redirect(url_for('manager_dashboard'))


@app.route('/manager/bulk_import_staff', methods=['POST'])
@login_required
@manager_required
def bulk_import_staff():
    if 'csv_file' not in request.files:
        flash('No file selected.', 'error')
        return redirect(url_for('manager_add_staff'))

    file = request.files['csv_file']
    if not file.filename.endswith('.csv'):
        flash('Please upload a valid .csv file.', 'error')
        return redirect(url_for('manager_add_staff'))

    try:
        stream = io.TextIOWrapper(file.stream, encoding='utf-8')
        reader = csv.DictReader(stream)

        imported_count = 0
        skipped_count = 0

        role_map = {
            'DRIVER': UserRole.DRIVER,
            'MECHANIC': UserRole.MECHANIC,
            'MANAGER': UserRole.MANAGER
        }

        for row in reader:
            email = row.get('email', '').strip().lower()
            full_name = row.get('full_name', '').strip()
            raw_pin = str(row.get('pin_code', '')).strip()
            role_str = row.get('role', 'Driver').strip().upper()

            if not email or not full_name or not raw_pin or User.query.filter_by(email=email).first():
                skipped_count += 1
                continue

            selected_role = role_map.get(role_str, UserRole.DRIVER)

            new_user = User(
                company_id=current_user.company_id,
                full_name=full_name,
                email=email,
                role=selected_role,
                licence_expiry_date=parse_date(row.get('licence_expiry_date')),
                cpc_expiry_date=parse_date(row.get('cpc_expiry_date')),
                is_active=True
            )
            new_user.set_pin(raw_pin)
            db.session.add(new_user)
            imported_count += 1

        db.session.commit()
        flash(f'Import complete: {imported_count} staff added ({skipped_count} skipped/duplicates).', 'success')

    except Exception as e:
        db.session.rollback()
        flash(f'Error processing CSV file: {str(e)}', 'error')

    return redirect(url_for('manager_dashboard'))


@app.route('/manager/vehicle/<int:vehicle_id>', methods=['GET', 'POST'])
@login_required
@manager_required
def manager_vehicle_detail(vehicle_id):
    vehicle = Vehicle.query.filter_by(vehicle_id=vehicle_id, company_id=current_user.company_id).first_or_404()

    if request.method == 'POST':
        reg_num = request.form.get('registration_number', '').strip().upper()
        make_model = request.form.get('make_model', '').strip()
        vehicle_type = request.form.get('vehicle_type')
        pmi_weeks = request.form.get('pmi_interval_weeks')
        current_status = request.form.get('current_status', 'Active').strip()

        existing = Vehicle.query.filter(Vehicle.registration_number == reg_num, Vehicle.vehicle_id != vehicle_id).first()
        if existing:
            flash('Another vehicle is already registered with this registration number.', 'error')
            return redirect(url_for('manager_vehicle_detail', vehicle_id=vehicle_id))

        vehicle.registration_number = reg_num
        vehicle.make_model = make_model
        vehicle.vehicle_type = vehicle_type
        vehicle.pmi_interval_weeks = int(pmi_weeks) if pmi_weeks else 13
        vehicle.current_status = current_status
        vehicle.next_cvrt_date = parse_date(request.form.get('next_cvrt_date'))
        vehicle.next_pmi_date = parse_date(request.form.get('next_pmi_date'))
        vehicle.tax_expiry_date = parse_date(request.form.get('tax_expiry_date'))
        vehicle.insurance_expiry_date = parse_date(request.form.get('insurance_expiry_date'))
        vehicle.tacho_calibration_date = parse_date(request.form.get('tacho_calibration_date'))

        db.session.commit()
        flash(f'Vehicle profile for {vehicle.registration_number} updated successfully.', 'success')
        return redirect(url_for('manager_vehicle_detail', vehicle_id=vehicle_id))

    walkarounds = (
        WalkaroundLog.query
        .filter_by(vehicle_id=vehicle.vehicle_id)
        .order_by(WalkaroundLog.created_at.desc())
        .limit(5)
        .all()
    )

    defects = (
        Defect.query
        .filter_by(vehicle_id=vehicle.vehicle_id)
        .order_by(Defect.defect_id.desc())
        .limit(5)
        .all()
    )

    return render_template('vehicle_detail.html', vehicle=vehicle, walkarounds=walkarounds, defects=defects)


@app.route('/manager/triage', methods=['GET', 'POST'])
@login_required
@manager_required
def manager_triage():
    active_mechanics = (
        User.query
        .filter(
            User.company_id == current_user.company_id,
            User.is_active == True,
            User.role == UserRole.MECHANIC
        )
        .order_by(User.full_name.asc())
        .all()
    )

    priority_order = case(
        (Defect.priority == 'High', 1),
        (Defect.priority == 'Medium', 2),
        (Defect.priority == 'Low', 3),
        else_=4
    )

    defects = (
        Defect.query.join(Vehicle)
        .filter(Vehicle.company_id == current_user.company_id, Defect.status != 'Resolved')
        .order_by(priority_order, Defect.defect_id.desc())
        .all()
    )

    if request.method == 'POST':
        defect_id = request.form.get('defect_id')
        action = request.form.get('action')
        new_priority = request.form.get('priority')
        mechanic_id = request.form.get('mechanic_id')
        deferral_reason = request.form.get('deferral_reason', '').strip()
        manager_sig = request.form.get('manager_signature', '').strip()

        defect = Defect.query.get_or_404(defect_id)
        vehicle = Vehicle.query.get(defect.vehicle_id)

        # 1. Manager Sets Priority Level
        if action == 'update_priority' and new_priority:
            defect.priority = new_priority
            flash(f'Defect #{defect.defect_id} priority set to {new_priority}.', 'info')

        # 2. Manager Assigns Repair Job to Active Mechanic
        elif action == 'assign_mechanic':
            if mechanic_id:
                mech_user = User.query.filter_by(user_id=int(mechanic_id), is_active=True).first()
                if mech_user:
                    repair_job = RepairJob.query.filter_by(defect_id=defect.defect_id).first()
                    if not repair_job:
                        repair_job = RepairJob(defect_id=defect.defect_id)
                        db.session.add(repair_job)

                    repair_job.assigned_mechanic_id = mech_user.user_id
                    repair_job.approving_manager_id = current_user.user_id

                    defect.triage_decision = True
                    if vehicle and vehicle.current_status != 'In Workshop':
                        vehicle.current_status = 'In Workshop'

                    flash(f'Defect #{defect.defect_id} assigned to mechanic {mech_user.full_name}.', 'success')

        # 3. Manager Defers Repair
        elif action == 'defer':
            if not deferral_reason:
                flash('Please provide a reason for deferring this repair.', 'error')
                return redirect(url_for('manager_triage'))

            defect.triage_decision = False
            defect.deferral_reason = deferral_reason
            flash(f'Defect #{defect.defect_id} repair deferred: "{deferral_reason}".', 'info')

        # 4. Manager Performs Final Approval & Sign-Off
        elif action == 'final_approval':
            if not manager_sig:
                flash('Manager signature is required for final approval.', 'error')
                return redirect(url_for('manager_triage'))

            repair_job = RepairJob.query.filter_by(defect_id=defect.defect_id).first()
            if repair_job:
                repair_job.final_manager_signature = manager_sig
                repair_job.approving_manager_id = current_user.user_id

            defect.status = 'Resolved'
            defect.triage_decision = True

            if vehicle:
                remaining_defects = Defect.query.filter(
                    Defect.vehicle_id == vehicle.vehicle_id,
                    Defect.status != 'Resolved',
                    Defect.defect_id != defect.defect_id
                ).count()

                if remaining_defects == 0:
                    vehicle.current_status = 'Active'

            flash(f'Defect #{defect.defect_id} signed off with final manager approval. {vehicle.registration_number if vehicle else "Vehicle"} restored to Active service.', 'success')

        db.session.commit()
        return redirect(url_for('manager_triage'))

    return render_template('manager_triage.html', defects=defects, active_mechanics=active_mechanics)


# ==========================================
# INSPECTION & WORKSHOP ROUTES
# ==========================================

@app.route('/driver/walkaround', methods=['GET', 'POST'])
@login_required
def walkaround_checklist():
    vehicles = Vehicle.query.filter_by(company_id=current_user.company_id, current_status='Active').all()

    if request.method == 'POST':
        vehicle_id = request.form.get('vehicle_id')
        odometer = request.form.get('odometer_reading')
        defect_details = request.form.get('defect_details', '').strip()

        if not vehicle_id:
            flash('Please select a vehicle registration.', 'error')
            return redirect(url_for('walkaround_checklist'))

        checklist_data = {}
        flagged_defects = []

        for i in range(1, 23):
            item_status = request.form.get(f'item_{i}', 'OK')
            checklist_data[f'item_{i}'] = item_status
            if item_status == 'Defect':
                flagged_defects.append(i)

        is_passed = len(flagged_defects) == 0

        try:
            walkaround_log = WalkaroundLog(
                company_id=current_user.company_id,
                vehicle_id=int(vehicle_id),
                user_id=current_user.user_id,
                current_odometer=int(odometer) if odometer else 0,
                is_roadworthy=is_passed,
                check_data=checklist_data
            )
            db.session.add(walkaround_log)
            db.session.flush()

            if not is_passed:
                photo_path = None

                if 'defect_photo' in request.files:
                    file = request.files['defect_photo']
                    if file and file.filename != '' and allowed_file(file.filename):
                        filename = secure_filename(f"defect_{vehicle_id}_{current_user.user_id}_{int(time.time())}.jpg")
                        file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
                        photo_path = f"uploads/defects/{filename}"

                primary_category_id = flagged_defects[0] if flagged_defects else 1

                defect_record = Defect(
                    log_id=walkaround_log.log_id,
                    vehicle_id=int(vehicle_id),
                    category_id=primary_category_id,
                    description=defect_details or f"Defects flagged on RSA items: {', '.join(map(str, flagged_defects))}",
                    photo_url=photo_path,
                    triage_decision=False,
                    status='Open'
                )
                db.session.add(defect_record)

                vehicle = Vehicle.query.get(int(vehicle_id))
                if vehicle:
                    vehicle.current_status = 'Defect Reported'

            db.session.commit()

            if is_passed:
                flash('Walkaround check submitted. Vehicle cleared for service.', 'success')
            else:
                flash('Walkaround check submitted with defects. Maintenance team notified.', 'error')

            return redirect(url_for('index'))

        except Exception as e:
            db.session.rollback()
            flash(f'Error submitting walkaround log: {str(e)}', 'error')
            return redirect(url_for('walkaround_checklist'))

    return render_template('walkaround_checklist.html', vehicles=vehicles)


@app.route('/mechanic/defects')
@login_required
def mechanic_console():
    user_role = (current_user.role.value if hasattr(current_user.role, 'value') else str(current_user.role)).upper()
    if user_role in ['MANAGER', 'ADMIN']:
        return redirect(url_for('manager_triage'))
    return redirect(url_for('mechanic_jobs'))


@app.route('/mechanic/jobs')
@login_required
def mechanic_jobs():
    user_role = (current_user.role.value if hasattr(current_user.role, 'value') else str(current_user.role)).upper()
    if user_role not in ['MECHANIC', 'ADMIN']:
        flash('Access restricted to Workshop Mechanics.', 'error')
        return redirect(url_for('index'))

    assigned_jobs = (
        RepairJob.query
        .join(Defect)
        .join(Vehicle)
        .filter(
            RepairJob.assigned_mechanic_id == current_user.user_id,
            Defect.status != 'Resolved'
        )
        .order_by(Defect.defect_id.desc())
        .all()
    )

    return render_template('mechanic_jobs.html', jobs=assigned_jobs)


@app.route('/mechanic/job/<int:job_id>', methods=['GET', 'POST'])
@login_required
def mechanic_job_detail(job_id):
    job = RepairJob.query.get_or_404(job_id)

    user_role = (current_user.role.value if hasattr(current_user.role, 'value') else str(current_user.role)).upper()
    if job.assigned_mechanic_id != current_user.user_id and user_role != 'ADMIN':
        flash('You are not authorized to view this assigned repair job.', 'error')
        return redirect(url_for('mechanic_jobs'))

    if request.method == 'POST':
        parts_replaced = 'parts_replaced' in request.form
        parts_cost_raw = request.form.get('parts_cost', '0.00').strip()
        repair_details = request.form.get('repair_details', '').strip()
        mechanic_sig = request.form.get('mechanic_signature', '').strip()

        if not mechanic_sig:
            flash('Please provide your mechanic sign-off signature.', 'error')
            return redirect(url_for('mechanic_job_detail', job_id=job.job_id))

        try:
            parts_cost = float(parts_cost_raw) if parts_cost_raw else 0.00
        except ValueError:
            parts_cost = 0.00

        job.parts_replaced = parts_replaced
        job.parts_cost = parts_cost
        job.repair_details = repair_details
        job.mechanic_signature = mechanic_sig

        # Submit job to Manager for Final Approval
        job.defect.status = 'Pending Approval'

        db.session.commit()
        flash(f'Repair job #{job.job_id} completed and submitted for Manager Final Approval.', 'success')
        return redirect(url_for('mechanic_jobs'))

    return render_template('mechanic_job_detail.html', job=job)



if __name__ == '__main__':
    app.run(debug=True, port=5001)