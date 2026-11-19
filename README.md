# EmoStudy 🧠😊

[![Python](https://img.shields.io/badge/Python-3.8%2B-blue.svg)](https://www.python.org/)
[![Flask](https://img.shields.io/badge/Flask-Web%20Framework-green.svg)](https://flask.palletsprojects.com/)
[![HTML5](https://img.shields.io/badge/HTML5-74%25-orange.svg)](https://developer.mozilla.org/en-US/docs/Web/Guide/HTML/HTML5)

**EmoStudy** is an innovative web-based learning application designed for primary school students aged 7–9. The platform utilizes real-time facial emotion recognition to detect how students feel during lessons and dynamically adjusts question difficulty or provides actionable insights in response.

---

## 🌟 Key Features

### 👨‍🎓 Student Interface
* **Live Learning Sessions:** Enables students to seamlessly join active learning sessions.
* **Real-Time Emotion Tracking:** Displays live emotion classification directly from the student's webcam feed.
* **Dynamic Questioning:** Automatically assigns and adapts questions based on the student's detected emotional state.
* **Minimalist Design:** Prioritizes simplicity and minimal cognitive load to ensure independent navigation without adult assistance.

### 👩‍🏫 Teacher Interface
* **Classroom Management:** Controls live learning sessions from a centralized dashboard.
* **Live Monitoring:** Monitors student webcam feeds and real-time emotion distributions concurrently.
* **Action Suggestions:** Provides intelligent pedagogical recommendations based on the current emotional state of the class.
* **Question Bank & Student Management:** Easily manage quiz questions and enrolled students from a single interface.

### 📊 Class Reports
* **Session Analytics:** Displays aggregated session statistics including total sessions, average accuracy, and total answers submitted.
* **Visual Trends:** Tracks accuracy and answer trends across sessions through intuitive charts.
* **Session History:** Views individual session histories complete with per-session accuracy tracking.
* **Data Export:** Allows teachers to export session data as CSV files for deeper offline analysis.

---

## 📁 Project Structure

```text
EmoStudy/
│
├── templates/              # HTML frontend templates (Student & Teacher views)
├── app.py                  # Main Flask application backend and routing
├── db.py                   # Database management and connection handlers
├── emotion_detector.py     # Real-time facial emotion recognition logic
├── emotion_labels.json     # Emotion mapping labels
├── model_best.keras        # Best trained emotion classification model weights
├── model_final.keras       # Final trained Keras emotion model
├── schema.sql              # Database schema definition
├── train_emotion_model.py  # Script for training the emotion detection model
├── test_emotion.py         # Testing script for emotion recognition accuracy
├── requirements.txt        # Python dependencies (if applicable)
└── README.md               # Project documentation

```

---

## 🛠️ Tech Stack & Requirements

* **Backend:** Python, Flask
* **Machine Learning / AI:** TensorFlow / Keras (Emotion Detection Model)
* **Frontend:** HTML5, CSS3, JavaScript
* **Database:** SQLite / Relational Database (Managed via `db.py`)
* **Computer Vision:** OpenCV / Web-based media stream for real-time facial emotion detection

---

## 🚀 Getting Started Locally

Follow these steps to set up and run the project on your local machine:

### 1. Clone the Repository

```bash
git clone [https://github.com/fiks67/EmoStudy.git](https://github.com/fiks67/EmoStudy.git)
cd EmoStudy

```

### 2. Install Dependencies

Make sure you have Python installed, then install the required packages:

```bash
pip install -r requirements.txt

```

*(Note: If `requirements.txt` is missing, ensure core packages like `flask`, `tensorflow`, `opencv-python`, and `numpy` are installed).*

### 3. Run the Application

Execute the main Flask application script:

```bash
python app.py

```

### 4. Access the Platform

Open your web browser and navigate to:

```text
http://localhost:5000

```

---

## 📸 Interface Previews

* **Student View:** Real-time emotion classification paired with adaptive learning questions.<img width="1723" height="748" alt="p" src="https://github.com/user-attachments/assets/c9b4035c-0f90-44df-ac58-9c30d0b5fc1d" />

* **Teacher View:** Live webcam monitoring, class emotion distribution, and automated action suggestions. <img width="953" height="870" alt="pp" src="https://github.com/user-attachments/assets/9222b433-d7b4-444f-a952-491f43114cc4" />

* **Class Reports:** Comprehensive analytics, visual trend charts, and CSV data exportation.<img width="1920" height="2453" alt="ppp" src="https://github.com/user-attachments/assets/e9d3887a-cbe0-4655-a3ed-7e60b1f96eef" />

---

## 👨‍💻 Author

* **Fikri Faqih Al Fawwaz** ([fiks67](https://www.google.com/search?q=https://github.com/fiks67))

```

```
