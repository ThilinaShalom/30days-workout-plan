from flask import Flask, render_template, request, redirect, url_for, session
import google.generativeai as genai
import os
import firebase_admin
from firebase_admin import credentials, firestore, auth


app = Flask(__name__)
app.secret_key = 'your_secret_key'  #Auto  Replace with a real secret key



# Initialize Firebase
cred = credentials.Certificate('firebase.json')
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

    # Fetch plans for the customer
    plans_ref = db.collection('plans').where('user_id', '==', session['user_id'])
    plans = [plan.to_dict() for plan in plans_ref.stream()]

    return render_template('customer_dashboard.html', plans=plans)

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
        
        # Save the plan to Firestore with a "requested" status
        db.collection('plans').add({
            'user_id': session['user_id'],
            'plan': workout_plan,
            'status': 'requested'
        })
        
        return render_template('result.html', workout_plan=workout_plan)
    return render_template('generate_form.html')

@app.route('/review_plan/<plan_id>', methods=['POST'])
def review_plan(plan_id):
    if 'user_id' not in session or session['user_type'] != 'coach':
        return redirect(url_for('login'))
    
    coach_comment = request.form['coach_comment']

    # Update the plan with the coach's comment and mark it as 'approved'
    plan_ref = db.collection('plans').document(plan_id)
    plan_ref.update({
        'coach_comment': coach_comment,
        'status': 'approved'
    })

    return redirect(url_for('coach_dashboard'))

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
