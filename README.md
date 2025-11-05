# 🕵️ Spy Game AI Edition (Kivy Mobile Game)

**Spy Game AI Edition** is a full-featured Kivy-based mobile implementation of the popular social deduction game, Spy, but with a few in-house rules added. This project elevates the standard game by integrating the **Gemini API** for dynamic content generation, ensuring endless replayability and a fresh experience every time.

The application is built entirely in Python using the Kivy framework, resulting in a stable, visually polished, and cross-platform mobile application ready for Android deployment.

---

## 🌟 Key Features

### 🧠 Gemini AI Powered Content Generation
* **Infinite Replayability:** Seamlessly integrates the Gemini API to generate **new categories and word pools** on demand.
* **Asynchronous Queries:** Network requests run in separate threads, ensuring the mobile GUI remains smooth and responsive during topic generation.
* **Secure API Handling:** Features a **runtime API key input screen**; the Gemini key is never embedded in the application code.

### 🎮 Advanced Game Modes & Logic
* **Dual Game Modes:** Supports **Easy Mode** (Caught Spies get a final guess) and **Hard Mode** (Spies win only upon achieving numerical parity).
* **Turn Skewing:** Implements an 85% chance for a Local to start Round 1, reducing meta-game predictability.
* **Word Pool Management:** Tracks used words across sessions and provides a **low-word-count warning** (at 10 words remaining) to prompt AI regeneration.
* **Multiple Spies:** Fully supports games with two or more spies.

### 🎨 UI/UX and Persistence
* **Player Library:** Developed a persistent library using `JsonStore` to manage, save, and reuse favorite player names dynamically.
* **Responsive Kivy UI:** Features a robust `wrap_label()` utility that dynamically calculates text size and ensures perfect text wrapping and alignment across all screens and device sizes.
* **Data Persistence:** Uses `JsonStore` to save player libraries and custom/AI-generated categories across application restarts.

---

## ⚙️ Technical Stack

* **Framework:** Kivy (Python)
* **Language:** Python 3.x
* **AI Integration:** Gemini API via the `requests` library
* **Deployment Target:** Android (via Buildozer)

---

## 🛠️ Setup and Running Locally

To run the application on your desktop for testing, you need Python and the Kivy framework.

### Prerequisites

1.  **Python 3.8+**
2.  **Kivy**
3.  **requests** library for API calls

### Local Installation

1.  **Clone the Repository:**
    ```bash
    git clone [https://github.com/YourUsername/WordSpyfallAIEdition.git](https://github.com/YourUsername/WordSpyfallAIEdition.git)
    cd WordSpyfallAIEdition
    ```
2.  **Set up a Virtual Environment (Recommended):**
    ```bash
    python -m venv venv
    source venv/bin/activate  # On Windows: venv\Scripts\activate
    ```
3.  **Install Dependencies:**
    ```bash
    pip install kivy requests
    ```
4.  **Run the Application:**
    ```bash
    python main.py
    ```
    The application will prompt you for your personal Gemini API Key on startup.

---

## 📦 Deployment (Android)

The project includes a fully configured `buildozer.spec` file, making Android deployment straightforward.

1.  **Install Buildozer:** `pip install buildozer`
2.  **Initialize (if not using the provided spec):** `buildozer init`
3.  **Build the APK:**
    ```bash
    buildozer android debug
    ```
    The resulting `.apk` file will be found in the `bin/` directory.

---

## 💡 Project Status

This project is in a **Final/Production** state. All core features, UI stability, and deployment readiness requirements have been resolved. The focus shifted from debugging UI artifacts to refining the core game loop and content generation mechanisms.
