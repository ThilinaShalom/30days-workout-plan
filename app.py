from flask import Flask, render_template, request, redirect, url_for, session, jsonify
import google.generativeai as genai
import os
import firebase_admin
from firebase_admin import credentials, firestore, auth
from google.api_core.exceptions import DeadlineExceeded
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

app = Flask(__name__)
app.config['JSON_AS_ASCII'] = False
app.secret_key = 'your_secret_key'  #Auto  Replace with a real secret key

# Initialize Firebase
cred = credentials.Certificate('hdproject-6e51c-firebase-adminsdk-4e5te-d7102a3fe3.json')
firebase_admin.initialize_app(cred)
db = firestore.client()

# Set your Gemini API key 
genai.configure(api_key=os.getenv('GENAI_API_KEY'))

# Initialize the Gemini model
model = genai.GenerativeModel('gemini-pro')

@app.route('/')
def home():
    return render_template('index.html')

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        email = request.form['email']
        password = request.form['password']
        user_type = request.form['user_type']
        try:
            user = auth.create_user(email=email, password=password)
            db.collection('users').document(user.uid).set({
                'email': email,
                'user_type': user_type
            })
            return redirect(url_for('login'))
        except Exception as e:
            return f'Registration failed: {str(e)}'
    return render_template('register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form['email']
        password = request.form['password']
        try:
            user = auth.get_user_by_email(email)
            user_data = db.collection('users').document(user.uid).get().to_dict()
            session['user_id'] = user.uid
            session['user_type'] = user_data['user_type']
            if user_data['user_type'] == 'customer':
                return redirect(url_for('customer_dashboard'))
            else:
                return redirect(url_for('coach_dashboard'))
        except Exception as e:
            return f'Login failed: {str(e)}'
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('home'))

@app.route('/customer_dashboard')
def customer_dashboard():
    if 'user_id' not in session or session['user_type'] != 'customer':
        return redirect(url_for('login'))

    # Fetch user data
    user_data = db.collection('users').document(session['user_id']).get().to_dict()
    user_name = user_data.get('name', 'Customer')  # Use 'Customer' as fallback if name is not set

    # Fetch plans for the customer
    plans_ref = db.collection('plans').where('user_id', '==', session['user_id'])
    plans = []
    for doc in plans_ref.stream():
        plan = doc.to_dict()
        plan['id'] = doc.id  # Add the document ID to the plan data
        plans.append(plan)

    return render_template('customer_dashboard.html', user_name=user_name, plans=plans)

@app.route('/coach_dashboard')
def coach_dashboard():
    if 'user_id' not in session or session['user_type'] != 'coach':
        return redirect(url_for('login'))

    # Fetch plans that have been sent for review
    plans_ref = db.collection('plans').where('status', '==', 'requested')
    plans = []
    for doc in plans_ref.stream():
        plan = doc.to_dict()
        plan['id'] = doc.id
        plans.append(plan)

    return render_template('coach_dashboard.html', plans=plans)

@app.route('/generate', methods=['GET', 'POST'])
def generate():
    if 'user_id' not in session or session['user_type'] != 'customer':
        return redirect(url_for('login'))

    if request.method == 'POST':
        user_info = {
            'age': request.form.get('age'),
            'weight_in_kg': request.form.get('weight_in_kg'),
            'height_in_cm': request.form.get('height_in_cm'),
            'fitness_goal': request.form.get('fitness_goal'),
            'fitness_level': request.form.get('fitness_level'),
            'Cholesterol_level': request.form.get('Cholesterol_level'),
            'Pressure_level': request.form.get('Pressure_level'),
            'Sugar_level': request.form.get('Sugar_level'),
            'equipment': request.form.get('equipment'),
            'days_per_week': request.form.get('days_per_week'),
            'Sleeping_Hours_per_day': request.form.get('Sleeping_Hours_per_day'),
            'diet_type': request.form.get('diet_type'),
            'allergies': request.form.get('allergies'),
            'meals_per_day': request.form.get('meals_per_day'),
        }
        workout_plan = generate_workout_plan(user_info)
        
        try:
            # Save the generated plan to Firestore without sending it to the coach
            db.collection('plans').add({
                'user_id': session['user_id'],
                'plan': workout_plan,
                'fitness_goal': user_info['fitness_goal'],
                'status': 'not_sent'
            }, timeout=30)  # Increase the timeout value (default is usually lower)
        except DeadlineExceeded:
            return "Firestore request timed out. Please try again later.", 504
        
        return render_template('result.html', workout_plan=workout_plan)
    return render_template('generate_form.html')

@app.route('/tell_coach/<plan_id>', methods=['POST'])
def tell_coach(plan_id):
    if 'user_id' not in session or session['user_type'] != 'customer':
        return jsonify({'error': 'Unauthorized'}), 401

    # Update the plan status to "requested" and mark it as sent to the coach
    try:
        plan_ref = db.collection('plans').document(plan_id)
        plan_doc = plan_ref.get()
        
        if not plan_doc.exists:
            return jsonify({'error': 'Plan not found'}), 404
        
        plan_data = plan_doc.to_dict()
        if plan_data['user_id'] != session['user_id']:
            return jsonify({'error': 'Unauthorized'}), 401
        
        plan_ref.update({
            'status': 'requested'
        })
        return jsonify({'success': True}), 200
    except Exception as e:
        print(f"Error in tell_coach: {str(e)}")  # Log the error
        return jsonify({'error': str(e)}), 500
    
@app.route('/review_plan/<plan_id>', methods=['POST'])
def review_plan(plan_id):
    if 'user_id' not in session or session['user_type'] != 'coach':
        return jsonify({'error': 'Unauthorized'}), 401
    
    coach_comment = request.form.get('coach_comment')
    action = request.form.get('action')

    print(f"Received data: plan_id={plan_id}, coach_comment={coach_comment}, action={action}")  # Debug log

    if not coach_comment or not action:
        print(f"Missing fields: coach_comment={coach_comment}, action={action}")  # Debug log
        return jsonify({'error': 'Missing required fields'}), 400

    plan_ref = db.collection('plans').document(plan_id)
    
    try:
        plan_doc = plan_ref.get()
        if not plan_doc.exists:
            return jsonify({'error': 'Plan not found'}), 404

        new_status = 'approved' if action == 'approve' else 'rejected'
        
        update_data = {
            'coach_comment': coach_comment,
            'status': new_status
        }
        print(f"Updating plan {plan_id} with data: {update_data}")  # Debug log
        plan_ref.update(update_data)
        
        print(f"Plan {plan_id} {new_status} successfully")
        return jsonify({'success': True, 'status': new_status}), 200
    except Exception as e:
        print(f"Error in review_plan: {str(e)}")
        return jsonify({'error': str(e)}), 500
    
@app.route('/delete_plan/<plan_id>', methods=['POST'])
def delete_plan(plan_id):
    if 'user_id' not in session or session['user_type'] != 'customer':
        return jsonify({'error': 'Unauthorized'}), 401

    plan_ref = db.collection('plans').document(plan_id)
    
    try:
        plan_doc = plan_ref.get()
        if not plan_doc.exists:
            return jsonify({'error': 'Plan not found'}), 404
        
        plan_data = plan_doc.to_dict()
        if plan_data['user_id'] != session['user_id']:
            return jsonify({'error': 'Unauthorized'}), 401
        
        plan_ref.delete()
        return jsonify({'success': True}), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 500

def generate_workout_plan(user_info):
    user_info_str = '\n'.join([f"{key.replace('_', ' ').title()}: {value}" for key, value in user_info.items()])
    prompt = f"""As a fitness expert, create a personalized 30-day workout plan and meal plan based on the following user information:

{user_info_str}

Please provide a detailed plan that includes exercises, sets, reps, and rest periods for each day."""
    response = model.generate_content(prompt)
    workout_plan = response.text
    return workout_plan

if __name__ == '__main__':
    app.run(debug=True)
