import os
import random
import json
import requests
import threading
from kivy.app import App
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.floatlayout import FloatLayout
from kivy.uix.button import Button
from kivy.uix.label import Label
from kivy.uix.checkbox import CheckBox
from kivy.uix.screenmanager import ScreenManager, Screen
from kivy.uix.popup import Popup
from kivy.uix.textinput import TextInput
from kivy.properties import StringProperty, NumericProperty, BooleanProperty, ListProperty
from kivy.clock import Clock
from kivy.core.window import Window
from kivy.config import Config
from kivy.metrics import dp
from kivy.storage.jsonstore import JsonStore
from kivy.uix.scrollview import ScrollView
from kivy.graphics import Color, Rectangle
import math # Import math for ceiling division logic

# Ensure responsive design for mobile (Kivy-specific setup)
from kivy.utils import platform

if platform == "android":
    Window.softinput_mode = "below_target"
else:
    Window.size = (400, 700)  # keep desktop default for testing

# --- THEME COLORS ---
DARK_BG = (0.1, 0.1, 0.1, 1) # Dark grey background
LIGHT_BG = (0.15, 0.15, 0.15, 1) # Slightly lighter background for elements
TEXT_PRIMARY = (1, 1, 1, 1) # White text
TEXT_SECONDARY = (0.7, 0.7, 0.7, 1) # Light grey text
ACCENT_BLUE = (0.3, 0.7, 0.9, 1) # Blue for Gemini
ACCENT_RED = (0.8, 0.3, 0.3, 1) # Red for Accuse
ACCENT_GREEN = (0.3, 0.8, 0.3, 1) # Green for Next Turn
ACCENT_YELLOW = (0.9, 0.8, 0.2, 1) # Yellow for single round

# Function to convert float RGB (0-1) to hex string (#RRGGBB)
def rgb_to_hex(r, g, b):
    # Convert 0-1 float to 0-255 int, then to 2-digit hex
    return '#{:02x}{:02x}{:02x}'.format(int(r*255), int(g*255), int(b*255))

# Pre-calculate the correct hex color tag string for use in .format() calls
TEXT_COLOR_TAG = rgb_to_hex(TEXT_PRIMARY[0], TEXT_PRIMARY[1], TEXT_PRIMARY[2])
# New hex color for accused players in single round mode (Yellow/Orange)
ACCUSED_COLOR_HEX = '#ffff99'

# --- Gemini API Configuration ---
# Leave the key as an empty string; the execution environment will provide credentials.
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
GEMINI_MODEL = "gemini-2.5-flash"
GEMINI_API_URL = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent?key={GEMINI_API_KEY}"

# --- Game Data ---
STORE_NAME = 'topic_data.json'
PLAYER_STORE_NAME = 'player_library.json'

# UPDATED to use proper nouns and specific, fixed locations/entities
GAME_TOPICS = {
    "Pop Culture": [
        "Times Square Billboard", "Star Trek Enterprise", "Hogwarts Great Hall", "The Millennium Falcon",
        "Nintendo Switch", "Oscar Awards Stage", "Taylor Swift Concert", "The Daily Show Set"
    ],
    "Geography": [
        "Mount Everest Base Camp", "Suez Canal", "Galapagos Islands", "Sahara Desert",
        "The Amazon River", "Tokyo Imperial Palace", "Machu Picchu Ruins", "The Great Barrier Reef"
    ],
    "USA": [
        "Statue of Liberty", "Yellowstone Geyser", "New York Stock Exchange", "White House Oval Office",
        "Golden Gate Bridge", "Wrigley Field Stadium", "Route 66 Diner", "Las Vegas Strip"
    ],
}

class SpyGame(BoxLayout):
    """
    Main game container managing state and Gemini API calls.
    """
    # Property to hold the user's key for the session
    session_api_key = StringProperty("")

    game_state = StringProperty("SETUP")
    current_player_name = StringProperty("Player 1")
    current_category = StringProperty("")
    secret_word = StringProperty("")
    is_current_player_spy = BooleanProperty(False)
    player_count = NumericProperty(3)
    spy_count = NumericProperty(1)
    time_remaining = NumericProperty(0)
    timer_event = None

    # Property for the current game mode. Added "SINGLE_ROUND".
    game_mode = StringProperty("EASY") # EASY, HARD, or SINGLE_ROUND

    # UI element for Gemini feedback
    gemini_status = StringProperty("")

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.orientation = 'vertical'
        self.spacing = dp(20)
        self.padding = dp(30)
        self.background_color = DARK_BG

        # Topic data storage
        self.store = JsonStore(STORE_NAME)

        # Load user-modified topics from storage
        stored_topics = self.store.get('topics').get('topics', {}) if self.store.exists('topics') else {}

        # Player data storage
        self.player_store = JsonStore(PLAYER_STORE_NAME)
        if self.player_store.exists('library'):
            # The .get('library') returns the dictionary stored under 'library'.
            # That dictionary contains the 'players' key.
            self.player_library = self.player_store.get('library').get('players', {})
        else:
            # If the 'library' key does not exist, initialize an empty dictionary.
            self.player_library = {}

        # Merge stored topics (and any user edits) with the default topics
        global GAME_TOPICS
        GAME_TOPICS = {**GAME_TOPICS, **stored_topics}

        # Update initial tracking based on the final GAME_TOPICS list
        self.selected_categories = list(GAME_TOPICS.keys())
        self.total_used_words = {cat: set() for cat in GAME_TOPICS.keys()}

        self.players = []
        self.name_inputs = [] # List to hold TextInput objects for player names

        # Persistent storage for player names. Increased to 20 for safety.
        self.player_names_list = [f"Player {i+1}" for i in range(20)]
        self.role_reveal_order = [] # Stores the randomized order of player indices for role viewing
        self.first_round_starter_index = 0

        # Persistent storage for category names
        self.selected_categories = list(GAME_TOPICS.keys())

        # Word pool management
        # Tracks words used in the current round's category
        self.used_words_in_current_category = set()
        # Tracks total words used per category across all rounds of this session
        self.total_used_words = {cat: set() for cat in GAME_TOPICS.keys()}

        # Single Round Mode State
        self.single_round_accusations = set() # To track the player indices accused in SR mode

        # --- UI Initialization ---
        self.sm = ScreenManager()
        self.ids['screen_manager'] = self.sm

        self.setup_screen = Screen(name='setup')
        self.role_assignment_screen = Screen(name='assign_role')
        self.game_screen = Screen(name='game_play')

        self.key_entry_screen = Screen(name='key_entry')
        self.key_entry_ui() # New method call

        self.sm.add_widget(self.setup_screen)
        self.sm.add_widget(self.role_assignment_screen)
        self.sm.add_widget(self.game_screen)
        self.sm.add_widget(self.key_entry_screen) # Add the new screen manager

        self.setup_ui()
        self.role_assignment_ui()
        self.game_ui()

        self.add_widget(self.sm)
        self.sm.current = 'setup'
        Window.bind(on_resize=self.on_window_resize)

        if GEMINI_API_KEY:
            self.session_api_key = GEMINI_API_KEY

        # The app should start on the key prompt screen if no key is present
        if not self.session_api_key:
            self.sm.current = 'key_entry'
        else:
            self.sm.current = 'setup'

    def on_window_resize(self, window, width, height):
        self.padding = dp(min(width, height) * 0.05)

    # --- UI Building Methods ---
    def key_entry_ui(self):
        layout = BoxLayout(orientation='vertical', spacing=dp(20), padding=dp(30))
        layout.canvas.before.add(kivy.graphics.Color(*DARK_BG))
        layout.canvas.before.add(kivy.graphics.Rectangle(size=layout.size, pos=layout.pos))

        layout.add_widget(Label(
            text="[b]GEMINI API KEY REQUIRED[/b]",
            font_size='22sp', markup=True, color=ACCENT_RED, size_hint_y=0.2
        ))
        layout.add_widget(Label(
            text="Please enter your personal Gemini API Key.\nIt will be stored for this session only.",
            font_size='16sp', color=TEXT_SECONDARY, size_hint_y=0.2
        ))

        self.ti_api_key = TextInput(
            text="", multiline=False, size_hint_y=None, height=dp(50),
            hint_text="AIzaSy...",
            foreground_color=TEXT_PRIMARY, background_color=(0.2, 0.2, 0.2, 1)
        )
        layout.add_widget(self.ti_api_key)

        btn_submit = self.wrap_button(
            text="SUBMIT KEY & CONTINUE",
            size_hint_y=0.1, height=dp(60), background_color=ACCENT_GREEN,
            on_press=self.submit_api_key
        )
        layout.add_widget(btn_submit)

        self.lbl_key_status = Label(text="", color=ACCENT_RED, size_hint_y=0.1)
        layout.add_widget(self.lbl_key_status)

        self.key_entry_screen.add_widget(layout)

    def submit_api_key(self, instance):
        key = self.ti_api_key.text.strip()
        if len(key) < 20 or not key.startswith('AIzaSy'):
            self.lbl_key_status.text = "ERROR: Invalid Key Format."
            return

        self.session_api_key = key
        self.lbl_key_status.text = ""
        self.sm.current = 'setup'

    def setup_ui(self):
        scroll_screen_container = ScrollView(do_scroll_x=False)

        layout = BoxLayout(
            orientation='vertical',
            spacing=dp(15),
            padding=dp(20),
            size_hint_y=None)
        layout.bind(minimum_height=layout.setter('height'))
        layout.canvas.before.add(kivy.graphics.Color(*DARK_BG))
        layout.canvas.before.add(kivy.graphics.Rectangle(size=layout.size, pos=layout.pos))

        title = Label(
            text="[b]WORD SPYFALL AI EDITION[/b]",
            font_size='24sp',
            markup=True,
            color=TEXT_PRIMARY,
            size_hint_y=0.1
        )
        layout.add_widget(title)

        # --- Game Mode Selector (Updated for SINGLE ROUND) ---
        layout.add_widget(self.wrap_label(text="Game Mode Selection:", size_hint_y=None, color=TEXT_SECONDARY))
        mode_control_layout = BoxLayout(size_hint_y=None, height=dp(50), spacing=dp(10))

        btn_easy = self.wrap_button(
            text="EASY",
            on_press=lambda x: self.set_game_mode("EASY"),
            height=dp(120),
            background_color=ACCENT_GREEN if self.game_mode == "EASY" else LIGHT_BG
        )
        btn_hard = self.wrap_button(
            text="HARD",
            on_press=lambda x: self.set_game_mode("HARD"),
            height=dp(120),
            background_color=ACCENT_RED if self.game_mode == "HARD" else LIGHT_BG
        )
        btn_single = self.wrap_button(
            text="SINGLE ROUND",
            on_press=lambda x: self.set_game_mode("SINGLE_ROUND"),
            height=dp(120),
            background_color=ACCENT_YELLOW if self.game_mode == "SINGLE_ROUND" else LIGHT_BG
        )

        self.btn_easy_mode = btn_easy
        self.btn_hard_mode = btn_hard
        self.btn_single_mode = btn_single

        mode_control_layout.add_widget(btn_easy)
        mode_control_layout.add_widget(btn_hard)
        mode_control_layout.add_widget(btn_single) # Add the new button
        layout.add_widget(mode_control_layout)
        # --- END : Game Mode Selector ---


        # Player Count Selector
        layout.add_widget(self.wrap_label(text="Total Players (Min 3):", size_hint_y=None, color=TEXT_SECONDARY))
        player_control_layout = BoxLayout(size_hint_y=None, height=dp(50), spacing=dp(10))

        btn_minus = Button(text="-", size_hint_x=0.3, on_press=lambda x: self.change_player_count(-1), background_color=LIGHT_BG)
        self.lbl_count = Label(text=str(self.player_count), size_hint_x=0.4, font_size='20sp', bold=True, color=TEXT_PRIMARY)
        btn_plus = Button(text="+", size_hint_x=0.3, on_press=lambda x: self.change_player_count(1), background_color=LIGHT_BG)

        player_control_layout.add_widget(btn_minus)
        player_control_layout.add_widget(self.lbl_count)
        player_control_layout.add_widget(btn_plus)
        layout.add_widget(player_control_layout)

        # Spy Count Selector
        layout.add_widget(self.wrap_label(text="Number of Spies (Max 1/3 Players):", size_hint_y=None, color=TEXT_SECONDARY))
        spy_control_layout = BoxLayout(size_hint_y=None, height=dp(50), spacing=dp(10))

        btn_spy_minus = Button(text="-", size_hint_x=0.3, on_press=lambda x: self.change_spy_count(-1), background_color=LIGHT_BG)
        self.lbl_spy_count = Label(text=str(self.spy_count), size_hint_x=0.4, font_size='20sp', bold=True, color=TEXT_PRIMARY)
        btn_spy_plus = Button(text="+", size_hint_x=0.3, on_press=lambda x: self.change_spy_count(1), background_color=LIGHT_BG)

        spy_control_layout.add_widget(btn_spy_minus)
        spy_control_layout.add_widget(self.lbl_spy_count)
        spy_control_layout.add_widget(btn_spy_plus)
        layout.add_widget(spy_control_layout)

        btn_manage_players = self.wrap_button(
            text="Manage Player Names",
            size_hint_y=None,
            height=dp(60),
            on_press=self.show_player_manager_popup,
            background_color=ACCENT_BLUE
        )
        layout.add_widget(btn_manage_players)

        # Regenerate Topic
        action_buttons_layout = BoxLayout(
            orientation='vertical',
            spacing=dp(10),
            size_hint_y=None,
            height=dp(250) # INCREASE HEIGHT to fit 4 buttons
        )

        # Library Button
        btn_library = self.wrap_button(
            text="OPEN PLAYER LIBRARY",
            size_hint_y=None,
            height=dp(60),
            on_press=self.show_library_manager_popup,
            background_color=ACCENT_BLUE
        )
        action_buttons_layout.add_widget(btn_library)

        btn_select_categories = Button(
            text="Select Categories for Round",
            size_hint_y=0.1,
            on_press=lambda x: self.show_category_selector(),
            background_color=ACCENT_BLUE
        )
        action_buttons_layout.add_widget(btn_select_categories)

        # Start Button
        btn_start = Button(text="START GAME", size_hint_y=0.2, on_press=self.start_game, background_color=ACCENT_GREEN)
        action_buttons_layout.add_widget(btn_start)

        # Button for regenerating an existing category via Gemini
        btn_regenerate = self.wrap_button(
            text="Regenerate Existing Category (Gemini)",
            size_hint_y=0.2,
            height=dp(60),
            background_color=ACCENT_BLUE,
            on_press=lambda x: self.show_regenerate_popup()
        )
        action_buttons_layout.add_widget(btn_regenerate)

        # Add the new container to the main layout
        layout.add_widget(action_buttons_layout)

        # Gemini Topic Generation Section
        self.lbl_gemini_status = Label(
            text=f"[color=808080]Available Categories:[/color] " + ", ".join(GAME_TOPICS.keys()),
            color=TEXT_SECONDARY,
            markup=True,
            size_hint_y=None,
            height=dp(50)
        )
        self.lbl_gemini_status.bind(
            width=lambda s, w: setattr(s, 'text_size', (w, None))
        )
        layout.add_widget(self.lbl_gemini_status)
        layout.add_widget(Label(size_hint_y=None, height=dp(10), text=''))

        btn_generate = self.wrap_button(
            text="Generate New Topics (via Gemini)",
            height=dp(60),
            on_press=self.show_generation_popup,
            background_color=ACCENT_BLUE
        )
        layout.add_widget(btn_generate)

        scroll_screen_container.add_widget(layout)
        self.setup_screen.add_widget(scroll_screen_container)

    def set_game_mode(self, mode):
        self.game_mode = mode
        # Update button colors dynamically
        self.btn_easy_mode.background_color = ACCENT_GREEN if mode == "EASY" else LIGHT_BG
        self.btn_hard_mode.background_color = ACCENT_RED if mode == "HARD" else LIGHT_BG
        self.btn_single_mode.background_color = ACCENT_YELLOW if mode == "SINGLE_ROUND" else LIGHT_BG

    def show_library_manager_popup(self, instance=None):
        content = BoxLayout(orientation='vertical', padding=dp(20), spacing=dp(10))
        content.canvas.before.add(Color(*LIGHT_BG))
        content.canvas.before.add(Rectangle(size=content.size, pos=content.pos))

        content.add_widget(self.wrap_label(text="[b]Player Library[/b] (Total: {})".format(len(self.player_library)), size_hint_y=None, color=TEXT_PRIMARY, font_size='18sp'))

        # --- Add New Player Section ---
        add_layout = BoxLayout(size_hint_y=None, height=dp(40), spacing=dp(10))
        self.ti_new_player = TextInput(hint_text="New Player Name (Optional: Image Path)", multiline=False, size_hint_x=0.7)
        btn_add = Button(text="ADD", size_hint_x=0.3, on_press=self.add_player_to_library, background_color=ACCENT_GREEN)
        add_layout.add_widget(self.ti_new_player)
        add_layout.add_widget(btn_add)
        content.add_widget(add_layout)
        # ----------------------------

        # --- Library List Section ---
        library_container = BoxLayout(orientation='vertical', spacing=dp(5), size_hint_y=None)
        library_container.bind(minimum_height=library_container.setter('height'))

        for name in sorted(self.player_library.keys()):
            row = BoxLayout(size_hint_y=None, height=dp(40), spacing=dp(10))
            row.add_widget(self.wrap_label(text=name, halign='left', height=dp(40), size_hint_x=0.7, size_hint_y=1.0))

            btn_remove = Button(text="REMOVE", size_hint_x=0.3, background_color=ACCENT_RED,
                                on_press=lambda x, n=name: self.remove_player_from_library(n))
            row.add_widget(btn_remove)
            library_container.add_widget(row)

        scroll_view = ScrollView(size_hint_y=0.7, do_scroll_x=False)
        scroll_view.add_widget(library_container)
        content.add_widget(scroll_view)
        # ----------------------------

        btn_close = self.wrap_button(text="CLOSE LIBRARY", size_hint_y=None, height=dp(50), on_press=lambda x: self.library_popup.dismiss(), background_color=ACCENT_BLUE)
        content.add_widget(btn_close)

        self.library_popup = Popup(title='Player Library', content=content, size_hint=(0.9, 0.9))
        self.library_popup.open()

    def add_player_to_library(self, instance):
        name = self.ti_new_player.text.strip()
        if name and name not in self.player_library:
            self.player_library[name] = {'image': None, 'custom': True}
            self.save_player_library()
            self.ti_new_player.text = "" # Clear input
            self.library_popup.dismiss()
            self.show_library_manager_popup() # Reopen to refresh list

    def remove_player_from_library(self, name):
        if name in self.player_library:
            del self.player_library[name]
            self.save_player_library()
            self.library_popup.dismiss()
            self.show_library_manager_popup() # Reopen to refresh list

    def show_player_manager_popup(self, instance):
        # 1. Create content layout
        popup_content = BoxLayout(orientation='vertical', padding=dp(20), spacing=dp(10))
        popup_content.canvas.before.add(kivy.graphics.Color(*LIGHT_BG))
        popup_content.canvas.before.add(kivy.graphics.Rectangle(size=popup_content.size, pos=popup_content.pos))

        popup_content.add_widget(self.wrap_label(
            text=f"Enter Names for {self.player_count} Players:",
            color=TEXT_PRIMARY, size_hint_y=None,
            font_size='18sp'
        ))

        popup_content.add_widget(Label(size_hint_y=None, height=dp(15), text=''))

        # 2. Recreate ScrollView/Container for names
        self.player_names_container_popup = BoxLayout(orientation='vertical', spacing=dp(5), size_hint_y=None)
        self.player_names_container_popup.bind(minimum_height=self.player_names_container_popup.setter('height'))

        # Add From Library button
        btn_add_from_library = self.wrap_button(
             text="ADD PLAYER FROM LIBRARY",
             size_hint_y=None, height=dp(40),
             on_press=lambda x: self.show_add_from_library_popup(popup), # Pass main popup for context
             background_color=ACCENT_BLUE
        )
        popup_content.add_widget(btn_add_from_library)

        scroll_view = ScrollView(size_hint_y=0.8, do_scroll_x=False)
        scroll_view.add_widget(self.player_names_container_popup)
        popup_content.add_widget(scroll_view)

        # Add OK button
        btn_ok = self.wrap_button(
            text="SAVE NAMES",
            size_hint_y=None, height=dp(60),
            on_press=lambda x: self.save_names_and_dismiss(popup),
            background_color=ACCENT_GREEN
        )
        popup_content.add_widget(btn_ok)

        # 4. Open popup
        popup = Popup(title='Manage Players', content=popup_content, size_hint=(0.9, 0.9))
        popup.open()

        self.update_player_name_inputs_for_popup()

    def remove_player_from_setup(self, index_to_remove):
        # 1. Save current names
        self.player_names_list = [ti.text.strip() for ti in self.name_inputs]

        # 2. Replace the name at the index with a default name
        self.player_names_list[index_to_remove] = f"Player {index_to_remove + 1}"

        # 3. Refresh the UI
        self.update_player_name_inputs_for_popup()

    def show_add_from_library_popup(self, setup_manager_popup):
        """
        Displays a popup listing library players not currently in the game setup.
        Allows the user to select a library player to add to the setup list.
        """
        content = BoxLayout(orientation='vertical', padding=dp(20), spacing=dp(10))
        content.canvas.before.add(Color(*LIGHT_BG))
        content.canvas.before.add(Rectangle(size=content.size, pos=content.pos))

        content.add_widget(self.wrap_label(text="[b]Select Player to Add[/b]", size_hint_y=None, color=TEXT_PRIMARY, font_size='18sp'))

        # Get names currently in the setup list to filter them out
        active_names = set(self.player_names_list[:self.player_count])

        library_list_container = BoxLayout(orientation='vertical', spacing=dp(5), size_hint_y=None)
        library_list_container.bind(minimum_height=library_list_container.setter('height'))

        # Filter library names: only show names NOT currently in the setup list
        available_library_players = sorted([
            name for name in self.player_library.keys() if name not in active_names
        ])

        if not available_library_players:
            library_list_container.add_widget(self.wrap_label(text="No players available in library.", color=TEXT_SECONDARY, size_hint_y=None, height=dp(40)))

        for name in available_library_players:
            btn = Button(
                text=name,
                size_hint_y=None, height=dp(50), background_color=(0.3, 0.4, 0.5, 1),
                # CRITICAL: Pass both popups to the final function
                on_press=lambda x, n=name: self.add_library_player_to_setup(n, add_popup, setup_manager_popup)
            )
            library_list_container.add_widget(btn)

        scroll_view = ScrollView(size_hint_y=0.7, do_scroll_x=False)
        scroll_view.add_widget(library_list_container)
        content.add_widget(scroll_view)

        btn_close = self.wrap_button(text="CANCEL", size_hint_y=None, height=dp(50), on_press=lambda x: add_popup.dismiss(), background_color=ACCENT_RED)
        content.add_widget(btn_close)

        add_popup = Popup(title='Add from Library', content=content, size_hint=(0.8, 0.8))
        add_popup.open()

    def add_library_player_to_setup(self, player_name, add_popup, setup_manager_popup):
        """
        Replaces the first available default name ('Player X') in the current setup
        with the selected library player's name.
        """
        # 1. Save current names from TextInputs first (if popup is open)
        if hasattr(self, 'name_inputs') and self.name_inputs:
            self.player_names_list = [ti.text.strip() for ti in self.name_inputs]

        # 2. Find the first generic name slot (e.g., "Player 3") and replace it
        replaced = False
        for i, name in enumerate(self.player_names_list[:self.player_count]):
             # Check if the name looks like a default name or is empty
             if name.startswith("Player ") or not name.strip():
                 self.player_names_list[i] = player_name
                 replaced = True
                 break

        # If no default slot found, append it (only if there's room, though player_count should restrict this)
        if not replaced and self.player_count < len(self.player_names_list):
            self.player_names_list[self.player_count] = player_name

        # 3. Dismiss both popups and refresh the main setup manager
        add_popup.dismiss()
        setup_manager_popup.dismiss()
        self.show_player_manager_popup(None)

    def update_player_name_inputs_for_popup(self):
        if not hasattr(self, 'player_names_container_popup'):
            return

        # This replaces the old update_player_name_inputs but targets the new popup container
        ROW_HEIGHT = dp(40)
        SPACING = dp(5)

        self.player_names_container_popup.clear_widgets()
        self.name_inputs = [] # Reinitialize name_inputs list

        if self.player_count > len(self.player_names_list):
             new_defaults = [f"Player {i+1}" for i in range(len(self.player_names_list), self.player_count)]
             self.player_names_list.extend(new_defaults)

        for i in range(self.player_count):
            default_name = self.player_names_list[i]

            row = BoxLayout(size_hint_y=None, height=ROW_HEIGHT, spacing=dp(5))
            ti = TextInput(
                text=default_name,
                multiline=False,
                size_hint_y=1.0,
                size_hint_x=0.7, # Reduced width to fit remove button
                height=ROW_HEIGHT,
                # ... (styling remains the same) ...
            )
            self.name_inputs.append(ti)
            row.add_widget(ti)

            btn_remove = Button(
                text="X", size_hint_x=0.3, background_color=ACCENT_RED,
                on_press=lambda x, idx=i: self.remove_player_from_setup(idx)
            )
            row.add_widget(btn_remove)
            self.player_names_container_popup.add_widget(row)

    def save_names_and_dismiss(self, popup):
        # Final Save: Make sure player_names_list is updated from TextInputs
        self.player_names_list = [ti.text.strip() for ti in self.name_inputs]
        popup.dismiss()

    def role_assignment_ui(self):
        float_layout = FloatLayout()

        layout = BoxLayout(orientation='vertical', spacing=dp(15), padding=dp(20))
        layout.size_hint = (1, 1)
        layout.pos_hint = {'x': 0, 'y': 0}
        layout.canvas.before.add(kivy.graphics.Color(*DARK_BG))
        layout.canvas.before.add(kivy.graphics.Rectangle(size=layout.size, pos=layout.pos))

        # Use the pre-calculated TEXT_COLOR_TAG
        self.lbl_pass_device = Label(
            # Text will be set in update_role_assignment_screen
            text="",
            markup=True,
            color=TEXT_PRIMARY,
            size_hint_y=0.4
        )
        layout.add_widget(self.lbl_pass_device)

        # Neutral instruction text
        self.lbl_player_info = self.wrap_label(text="Tap 'View Role' to check your identity.", size_hint_y=None, height=dp(50), color=TEXT_SECONDARY)
        layout.add_widget(self.lbl_player_info)

        btn_view_role = self.wrap_button(text="VIEW ROLE", size_hint_y=0.2, height=dp(60), on_press=self.show_role_popup, background_color=ACCENT_BLUE)
        layout.add_widget(btn_view_role)

        btn_next_player = self.wrap_button(text="FINISHED VIEWING - HIDE ROLE", size_hint_y=0.2, height=dp(60), on_press=self.next_player_assignment, background_color=ACCENT_GREEN)
        layout.add_widget(btn_next_player)

        float_layout.add_widget(layout) # Add content layout first

        # Add the QUIT button
        btn_quit = Button(
            text="[b]QUIT[/b]",
            markup=True,
            font_size='14sp',
            size_hint=(None, None),
            size=(dp(70), dp(40)),
            pos_hint={'x': 0.03, 'top': 0.98}, # Top Left Corner
            background_color=ACCENT_RED,
            on_press=self.show_quit_popup # Use the existing quit handler
        )
        float_layout.add_widget(btn_quit)

        # Add the FloatLayout (which contains everything) to the screen
        self.role_assignment_screen.add_widget(float_layout)

    def game_ui(self):
        float_layout = FloatLayout()

        layout = BoxLayout(orientation='vertical', spacing=dp(15), padding=dp(20))

        layout.size_hint = (1, 1)
        layout.pos_hint = {'x': 0, 'y': 0}
        layout.canvas.before.add(kivy.graphics.Color(*DARK_BG))
        layout.canvas.before.add(kivy.graphics.Rectangle(size=layout.size, pos=layout.pos))

        layout.add_widget(Label(size_hint_y=None, height=dp(20), text=''))

        self.lbl_game_status = Label(
            text="[b]Turn:[/b] {player}".format(player=self.current_player_name),
            markup=True,
            font_size='18sp',
            color=TEXT_PRIMARY,
            size_hint_y=None, height=dp(70)
        )
        layout.add_widget(self.lbl_game_status)

        self.lbl_turn_instruction = self.wrap_label(
            text="[b]Clue Time![/b]\n\nSay a single word or short phrase related to the secret word.",
            font_size='20sp',
            color=TEXT_PRIMARY,
            height=dp(60),
            valign='middle',
            halign='center'
        )
        layout.add_widget(self.lbl_turn_instruction)

        # Button for the current player to secretly view their role/word during the turn
        control_layout = BoxLayout(size_hint_y=0.15, spacing=dp(10))

        self.btn_check_role = self.wrap_button(
            text="CHECK YOUR ROLE / SECRET WORD",
            size_hint_y=None,
            height=dp(50),
            on_press=self.show_current_turn_role_popup,
            background_color=ACCENT_BLUE
        )

        self.btn_accuse = Button(
            text="ACCUSE PLAYER",
            on_press=self.show_accuse_popup,
            size_hint_y=None,
            background_color=ACCENT_RED
        )

        control_layout.add_widget(self.btn_check_role)
        control_layout.add_widget(self.btn_accuse)
        layout.add_widget(control_layout)

        float_layout.add_widget(layout)
        btn_quit = Button(
            text="[b]QUIT[/b]",
            markup=True,
            font_size='14sp',
            size_hint=(None, None),
            size=(dp(70), dp(40)),
            pos_hint={'x': 0.03, 'top': 0.98}, # Top Left Corner
            background_color=ACCENT_RED,
            on_press=self.show_quit_popup
        )
        float_layout.add_widget(btn_quit)

        self.game_screen.add_widget(float_layout)

    def show_current_turn_role_popup(self, instance):
        """Displays the role and word specific to the current player whose turn it is."""
        player_idx = self.current_player_index % self.player_count
        player_data = self.players[player_idx]

        # --- Use the logic from show_role_popup to generate secure text ---

        # 1. Determine role text
        if player_data['is_spy']:
            role_text = "[b][color=ff5555]YOU ARE THE SPY[/color][/b]"
            main_info = f"Category: [b]{self.current_category}[/b]\n\nSecret Word: [color=ff5555]???[/color]\n\nGoal: Bluff and guess the word."
        else:
            role_text = "[b][color=55ff55]YOU ARE A LOCAL[/color][/b]"
            main_info = f"Category: [b]{self.current_category}[/b]\n\nSecret Word: [b][size=24sp]{self.secret_word}[/size][/b]\n\nGoal: Find the Spy without revealing the word."

        # 2. Build content box
        content = BoxLayout(orientation='vertical', padding=dp(20), spacing=dp(20))
        content.canvas.before.add(kivy.graphics.Color(*LIGHT_BG))
        content.canvas.before.add(kivy.graphics.Rectangle(size=content.size, pos=content.pos))

        content.add_widget(Label(text=f"[b]Turn For:[/b] {player_data['name']}", markup=True, size_hint_y=0.15, color=TEXT_PRIMARY))
        content.add_widget(
            Label(
                text=role_text,
                markup=True,
                size_hint_y=0.15,
                color=TEXT_PRIMARY,
                text_size=(dp(280), None),
                halign='center',
                valign='top'
                ))

        # Display main game information (Category/Word)
        content.add_widget(
            Label(
                text=main_info,
                markup=True,
                size_hint_y=0.5,
                font_size='18sp',
                color=TEXT_PRIMARY,
                text_size=(dp(280), None),
                halign='center',
                valign='top'
                ))

        btn_close = self.wrap_button(text="CLOSE AND HIDE SCREEN", size_hint_y=0.2, height=dp(60), on_press=lambda x: popup.dismiss(), background_color=ACCENT_GREEN)
        content.add_widget(btn_close)

        popup = Popup(title='YOUR TURN INFORMATION (HIDE IMMEDIATELY!)', content=content, size_hint=(0.9, 0.7))
        popup.open()

    def show_quit_popup(self, instance):
        content = BoxLayout(orientation='vertical', padding=dp(20), spacing=dp(20))
        content.canvas.before.add(kivy.graphics.Color(*LIGHT_BG))
        content.canvas.before.add(kivy.graphics.Rectangle(size=content.size, pos=content.pos))

        w = Window.width # Use window width for text_size calculation
        content.add_widget(
            self.wrap_label(
                text="Are you sure you want to end the game? All progress will be lost.",
                markup=True,
                size_hint_y=0.4,
                color=TEXT_PRIMARY,
                font_size='18sp',
                text_size=(w*0.95, None),
                halign='center',
                valign='middle'
                )
            )

        reset_control_layout = BoxLayout(size_hint_y=None, height=dp(40), spacing=dp(10))
        self.chk_preserve_config = CheckBox(active=True, size_hint_x=0.2)
        lbl_reset = Label(
            text="[b]Keep Players & Mode[/b]",
            markup=True, color=TEXT_SECONDARY, halign='left', valign='middle', size_hint_x=0.8
        )
        reset_control_layout.add_widget(self.chk_preserve_config)
        reset_control_layout.add_widget(lbl_reset)
        content.add_widget(reset_control_layout)

        control_layout = BoxLayout(size_hint_y=0.3, spacing=dp(10))

        btn_confirm = Button(
            text="END GAME",
            background_color=ACCENT_RED,
            on_press=lambda x: self.quit_game(popup, self.chk_preserve_config.active)
        )
        btn_cancel = Button(
            text="RESUME",
            background_color=ACCENT_GREEN,
            on_press=lambda x: self.resume_game(popup) # Reuse existing logic
        )

        control_layout.add_widget(btn_confirm)
        control_layout.add_widget(btn_cancel)
        content.add_widget(control_layout)

        popup = Popup(title='CONFIRM QUIT', content=content, size_hint=(0.8, 0.5))
        popup.open()

    def quit_game(self, popup, preserve_config):
        popup.dismiss()
        # Pass the state of the checkbox directly to reset_game
        self.reset_game(None, preserve_config=preserve_config)

    # --- Game Logic Methods ---
    def change_player_count(self, change):
        if self.name_inputs:
            self.player_names_list = [ti.text.strip() for ti in self.name_inputs]

        # 2. Update count
        new_count = self.player_count + change
        # REMOVED MAX LIMIT OF 10
        if new_count >= 3:
            self.player_count = new_count
            self.lbl_count.text = str(self.player_count)

            # 3. Adjust spy count if player count drops below min requirement
            max_spies = math.floor(self.player_count / 3)
            if self.spy_count > max_spies:
                self.spy_count = max_spies
                self.lbl_spy_count.text = str(self.spy_count)
            # Ensure minimum 1 spy if possible
            if self.spy_count == 0 and self.player_count >= 3:
                 self.spy_count = 1
                 self.lbl_spy_count.text = str(self.spy_count)


            # 4. Update inputs using saved names
            self.update_player_name_inputs_for_popup()

    def change_spy_count(self, change):
        max_spies = math.floor(self.player_count / 3)
        new_count = self.spy_count + change

        if 1 <= new_count <= max_spies:
            self.spy_count = new_count
            self.lbl_spy_count.text = str(self.spy_count)

    def save_player_library(self):
        """Saves the current state of the player library to JsonStore."""
        self.player_store.put('library', players=self.player_library)

    def start_game(self, instance):
        # 1. Final Save: Make sure player_names_list is updated from TextInputs
        self.player_names_list = [ti.text.strip() for ti in self.name_inputs]

        # 2. Initialize players with custom names
        player_names = [name for name in self.player_names_list[:self.player_count] if name]
        if len(player_names) != self.player_count:
             # Fallback for any empty names
             player_names = [f"Player {i+1}" for i in range(self.player_count)]

        # Initialize all players as active
        self.players = [{'name': name, 'is_spy': False, 'is_spy_active': True} for name in player_names]

        # 3. Assign roles (Multiple spies)
        spy_indices = random.sample(range(self.player_count), self.spy_count)
        for i in spy_indices:
            self.players[i]['is_spy'] = True

        # 4. Create and shuffle the list of player indices for role viewing
        self.role_reveal_order = list(range(self.player_count))
        random.shuffle(self.role_reveal_order)

        # 5. Choose topic
        categories = getattr(self, 'selected_categories', list(GAME_TOPICS.keys()))
        category_name = random.choice(categories)
        # --- Word Selection Logic ---

        # Get all words not used in this category yet
        available_words = list(set(GAME_TOPICS[category_name]) - self.total_used_words.get(category_name, set()))

        if not available_words:
            # If all words have been used, reset the pool for this category
            self.total_used_words[category_name] = set()
            available_words = GAME_TOPICS[category_name]

        self.current_category = category_name
        self.secret_word = random.choice(available_words)

        # Track the word as used for the session
        self.total_used_words.setdefault(category_name, set()).add(self.secret_word)

        # --- END WORD SELECTION LOGIC ---

        # 6. Create and shuffle the list of player indices for role viewing
        self.role_reveal_order = list(range(self.player_count))
        random.shuffle(self.role_reveal_order)

        self.current_player_index = 0 # Start with the first player in the randomized order

        # --- Perform FIRST ROUND START SKEWING LOGIC HERE (Only for long modes) ---
        if self.game_mode != "SINGLE_ROUND":
            # Skews the first turn starter away from a Spy (85% chance) for better game balance.
            active_player_indices = list(range(self.player_count))
            start_idx = random.choice(active_player_indices)
            is_start_spy = self.players[start_idx]['is_spy']

            # Skewing logic: 85% chance to re-roll if the starting player is a Spy
            if is_start_spy and random.random() < 0.85:
                local_indices = [i for i in active_player_indices if not self.players[i]['is_spy']]
                if local_indices:
                    self.first_round_starter_index = random.choice(local_indices)
                else:
                    self.first_round_starter_index = start_idx # Keep Spy if no Locals left
            else:
                self.first_round_starter_index = start_idx
        else:
            # Single Round mode doesn't need turn skewing, set starter arbitrarily
            self.first_round_starter_index = 0
        # --- END FIRST ROUND START SKEWING LOGIC ---

        self.current_player_index = 0 # Start with the first player in the randomized order
        self.update_role_assignment_screen()
        self.sm.current = 'assign_role'

    def show_category_selector(self):
        content = BoxLayout(orientation='vertical', padding=dp(20), spacing=dp(10))
        content.canvas.before.add(kivy.graphics.Color(*LIGHT_BG))
        content.canvas.before.add(kivy.graphics.Rectangle(size=content.size, pos=content.pos))

        content.add_widget(self.wrap_label(text="Select categories for this round:", color=TEXT_PRIMARY, size_hint_y=None, height=dp(60)))

        category_container = BoxLayout(orientation='vertical', size_hint_y=None, spacing=dp(5))
        category_container.bind(minimum_height=category_container.setter('height'))

        for cat in GAME_TOPICS.keys():
            is_active = cat in self.selected_categories
            row = BoxLayout(size_hint_y=None, height=dp(40))
            chk = CheckBox(active=is_active)
            lbl = Label(text=cat, color=TEXT_PRIMARY)
            chk.bind(active=lambda checkbox, value, c=cat: self.toggle_category(c, value))
            row.add_widget(chk)
            row.add_widget(lbl)
            category_container.add_widget(row)

        scroll = ScrollView(size_hint_y=0.7)
        scroll.add_widget(category_container)
        content.add_widget(scroll)

        popup = Popup(title='Choose Categories', size_hint=(0.9, 0.9))

        btn_ok = self.wrap_button(text="CONFIRM SELECTION", background_color=ACCENT_GREEN,
                        size_hint_y=None, height=dp(50),
                        on_press=lambda x: self.confirm_categories(popup))
        content.add_widget(btn_ok)

        popup = Popup(title='Choose Categories', content=content, size_hint=(0.9, 0.9))
        popup.open()

    def toggle_category(self, cat, value):
        if value:
            if cat not in self.selected_categories:
                self.selected_categories.append(cat)
        else:
            if cat in self.selected_categories:
                self.selected_categories.remove(cat)

    def confirm_categories(self, popup):
        popup.dismiss()
        if not self.selected_categories:
            self.selected_categories = list(GAME_TOPICS.keys())  # fallback

    def update_role_assignment_screen(self):
        # Use the index from the shuffled list
        if self.current_player_index < len(self.role_reveal_order):
            player_idx = self.role_reveal_order[self.current_player_index]
            self.current_player_name = self.players[player_idx]['name']

            self.lbl_pass_device.text = (
                f"[b]Pass Device to:[/b]\n"
                f"[color={TEXT_COLOR_TAG}][size=36sp]{self.current_player_name}[/size][/color]"
            )
            # Ensure view role button is visible
            self.lbl_player_info.text = "Tap 'View Role' to check your identity."
        else:
            # All roles revealed. Transition to the next phase based on game mode.

            # --- SINGLE ROUND MODE ACTIVATION ---
            if self.game_mode == "SINGLE_ROUND":
                self.single_round_accusations = set() # Reset accusation tracker
                self.show_single_round_accusation_popup()
                return
            # --- END SINGLE ROUND MODE ACTIVATION ---

            # Standard Modes (EASY/HARD): Start the discussion phase.
            self.current_player_index = 0 # Reset to the start of the natural order for turns
            self.current_player_name = self.players[self.first_round_starter_index]['name']

            # Neutral screen for game start
            self.lbl_pass_device.text = (
                f"[b]IT IS NOW TIME TO BEGIN![/b]\n"
                f"[color={TEXT_COLOR_TAG}][size=30sp]Pass Device to {self.current_player_name}[/size][/color]"
            )
            # Change instruction to reflect that the viewing phase is over
            self.lbl_player_info.text = "All roles assigned. Tap 'Finished Viewing - Hide Role' to start the first turn."

    def show_role_popup(self, instance):
        # Use the index from the shuffled list if still in the assignment phase
        if self.current_player_index < len(self.role_reveal_order):
            player_idx = self.role_reveal_order[self.current_player_index]
        else:
            # If accidentally clicked during the turn phase, use the current turn index
            player_idx = self.current_player_index % self.player_count

        player_data = self.players[player_idx]
        self.is_current_player_spy = player_data['is_spy']

        content = BoxLayout(orientation='vertical', padding=dp(20), spacing=dp(20))
        content.canvas.before.add(kivy.graphics.Color(*LIGHT_BG))
        content.canvas.before.add(kivy.graphics.Rectangle(size=content.size, pos=content.pos))


        if player_data['is_spy']:
            role_text = "[b][color=ff5555]YOU ARE THE SPY[/color][/b]\n\n"

            other_spies = [p['name'] for i, p in enumerate(self.players)
                           if p['is_spy'] and i != player_idx]

            if other_spies:
                spy_names = ", ".join(other_spies)
                role_text += f"Your fellow Spies are: [b][color={TEXT_COLOR_TAG}]{spy_names}[/color][/b]\n\n"
            else:
                role_text += "You are the only Spy this round.\n\n"

            main_info = f"Category: [b]{self.current_category}[/b]\n\nSecret Word: [color=ff5555]???[/color]\n\nGoal: Bluff and guess the word."

            if self.game_mode == "EASY":
                 main_info += "\n[color=ffff00]Mode: Easy (Final Guess Available)[/color]"
            elif self.game_mode == "HARD":
                 main_info += "\n[color=ffff00]Mode: Hard (Survive Only)[/color]"
            elif self.game_mode == "SINGLE_ROUND":
                 main_info += "\n[color=ffff00]Mode: Single Round (No Turns, Instant Accusation)[/color]"


        else:
            role_text = "[b][color=55ff55]YOU ARE A LOCAL[/color][/b]\n\nYour Goal: Find the Spy without revealing the Secret Word."
            main_info = f"Category: [b]{self.current_category}[/b]\n\nSecret Word: [b][size=30sp]{self.secret_word}[/size][/b]"
            if self.game_mode == "SINGLE_ROUND":
                 main_info += "\n[color=ffff00]Mode: Single Round (No Turns, Instant Accusation)[/color]"


        # Display the current player's name clearly at the top of the secret role pop-up
        player_label = Label(text=f"[b]Name:[/b] [color={TEXT_COLOR_TAG}][size=22sp]{player_data['name']}[/size][/color]",
                             markup=True, size_hint_y=0.15, color=TEXT_PRIMARY)
        content.add_widget(player_label)

        content.add_widget(Label(
            text=role_text,
            markup=True,
            size_hint_y=0.3,
            color=TEXT_PRIMARY,
            text_size=(dp(280), None),
            halign='center',
            valign='top'
        ))

        content.add_widget(Label(
            text=main_info,
            markup=True,
            size_hint_y=0.5,
            font_size='18sp',
            color=TEXT_PRIMARY,
            text_size=(dp(280), None),
            halign='center',
            valign='top'
        ))

        btn_close = self.wrap_button(text="I HAVE SEEN MY ROLE. CLOSE & HIDE", size_hint_y=0.2, height=dp(60), on_press=lambda x: popup.dismiss(), background_color=ACCENT_GREEN)
        content.add_widget(btn_close)

        # Popup does not support background_color property. It is styled via the window.
        popup = Popup(title='YOUR SECRET ROLE', content=content, size_hint=(0.9, 0.7))
        popup.open()

    def next_player_assignment(self, instance):
        self.current_player_index += 1

        if self.current_player_index < len(self.role_reveal_order):
            self.update_role_assignment_screen()
        else:
            # All roles have been seen (end of randomized list)

            # --- SINGLE ROUND MODE: Move to Accusation ---
            if self.game_mode == "SINGLE_ROUND":
                self.single_round_accusations = set() # Reset accusation tracker
                self.show_single_round_accusation_popup()
                return
            # --- END SINGLE ROUND MODE ---

            # Standard Modes (EASY/HARD): Start the discussion phase.
            self.current_player_index = self.first_round_starter_index # Set the starting player index for Round 1
            self.update_game_screen() # Sets up the first turn
            self.sm.current = 'game_play'

    # --- SINGLE ROUND MODE ACCUSATION HANDLER ---
    def show_single_round_accusation_popup(self):
        # This is the main screen for the Single Round Mode.
        content = BoxLayout(orientation='vertical', padding=dp(20), spacing=dp(20))
        content.canvas.before.add(kivy.graphics.Color(*LIGHT_BG))
        content.canvas.before.add(kivy.graphics.Rectangle(size=content.size, pos=content.pos))

        accused_count = len(self.single_round_accusations)
        required_count = self.spy_count

        # Build the list of accused player names with the new color
        accused_names = [self.players[i]['name'] for i in self.single_round_accusations]
        accused_list_str = f"[color={ACCUSED_COLOR_HEX}]{', '.join(accused_names)}[/color]"

        if accused_count == 0:
            instruction_text = (
                f"[b]SINGLE ROUND MODE ACTIVE[/b]\n\n"
                f"Discussion is over! The Town must now collectively identify {required_count} Spies "
                f"by making exactly {required_count} accusation(s)."
            )
        else:
            # Display already accused players with the new bright color
            instruction_text = (
                f"[b]ACCUSATION {accused_count} of {required_count}[/b]\n\n"
                f"You have already accused: {accused_list_str}\n\n"
                f"Choose the next person to accuse."
            )

        content.add_widget(self.wrap_label(
            text=instruction_text,
            size_hint_y=None,
            color=TEXT_PRIMARY,
            font_size='18sp',
            height=dp(100)
        ))

        # --- Scrollable Player List Setup ---
        player_list_container = BoxLayout(orientation='vertical', spacing=dp(5), size_hint_y=None)

        # Only show players who have NOT been accused yet
        available_players = [
            (i, p) for i, p in enumerate(self.players)
            if i not in self.single_round_accusations
        ]

        # Set height based on number of available players
        player_list_container.height = len(available_players) * dp(55)

        for original_index, player in available_players:
            # Buttons are always red (accusation button color)
            btn = Button(
                text=player['name'],
                on_press=lambda x, p_index=original_index: self.record_single_round_accusation(p_index, self.single_round_popup),
                size_hint_y=None, height=dp(50), background_color=ACCENT_RED
            )
            player_list_container.add_widget(btn)

        # 3. ScrollView to wrap the inner BoxLayout
        scroll_view = ScrollView(size_hint_y=0.7, do_scroll_x=False)
        scroll_view.add_widget(player_list_container)

        content.add_widget(scroll_view)
        # --- END Player List Setup ---

        btn_quit = self.wrap_button(text="END GAME (Quit to Setup)", on_press=lambda x: self.quit_game(self.single_round_popup, preserve_config=True), background_color=ACCENT_RED, size_hint_y=0.2, height=dp(60))
        content.add_widget(btn_quit)

        self.single_round_popup = Popup(title=f'ACCUSATION ({accused_count} of {required_count})', content=content, size_hint=(0.8, 0.9), auto_dismiss=False)
        self.single_round_popup.open()

    def record_single_round_accusation(self, accused_index, popup):
        """Records an accusation and either loops or resolves the game."""

        self.single_round_accusations.add(accused_index)

        if len(self.single_round_accusations) < self.spy_count:
            # Not enough accusations made, refresh the popup to choose the next one
            popup.dismiss()
            self.show_single_round_accusation_popup()
        else:
            # All required accusations have been made, resolve the round
            popup.dismiss()
            self.resolve_single_round_accusation()

    def resolve_single_round_accusation(self):
        """Checks if the accused set perfectly matches the spy set."""

        spy_indices = {i for i, p in enumerate(self.players) if p['is_spy']}

        # The accusations must exactly match the spy indices
        correctly_identified_spies = self.single_round_accusations.intersection(spy_indices)

        is_local_win = len(correctly_identified_spies) == self.spy_count and len(self.single_round_accusations) == self.spy_count

        if is_local_win:
            # Locals win: Guessed all spies and no locals.
            result_text = (
                f"PERFECT ACCUSATION!\n\n"
                f"The town correctly identified all {self.spy_count} Spies: "
                f"[b]{', '.join(self.players[i]['name'] for i in spy_indices)}[/b].\n\n"
                f"[b]LOCALS WIN![/b]"
            )
            self.show_result_popup("Locals", result_text)
        else:
            # Spies win: Either a local was wrongly accused, or a spy was missed.
            missed_spies = spy_indices - self.single_round_accusations
            wrongly_accused_locals = self.single_round_accusations - spy_indices

            summary = []
            if missed_spies:
                summary.append(f"{len(missed_spies)} Spy(s) missed.")
            if wrongly_accused_locals:
                summary.append(f"{len(wrongly_accused_locals)} Local(s) wrongly accused.")

            result_text = (
                f"MISSION FAILED!\n\n"
                f"The Town was unable to identify all spies correctly in a single round. ({' & '.join(summary)})\n\n"
                f"The Spies were: [b]{', '.join(self.players[i]['name'] for i in spy_indices)}[/b].\n"
                f"The Secret Word was: [b]{self.secret_word}[/b].\n\n"
                f"[b]SPIES WIN![/b]"
            )

            # Since it's Single Round, Spies win automatically if the Locals fail
            self.show_result_popup("Spy", result_text)

    # --- END SINGLE ROUND MODE HANDLER ---


    def start_timer(self, minutes):
        self.time_remaining = minutes * 60
        self.timer_event = Clock.schedule_interval(self.update_timer, 1)

    def update_timer(self, dt):
        self.time_remaining -= 1
        self.lbl_game_status.text = f"[b]Time:[/b] {self.time_remaining}s | [b]Turn:[/b] {self.current_player_name}"

        if self.time_remaining <= 0:
            if self.timer_event: self.timer_event.cancel()
            # If time runs out, automatically trigger the accusation/vote
            self.end_game_by_time()

    def update_game_screen(self):
        # This function is ONLY used by EASY/HARD modes
        if self.game_mode == "SINGLE_ROUND":
            # This should never be called in SR mode after role assignment, but included for safety.
            self.show_single_round_accusation_popup()
            return

        # --- Skip inactive players and loop until an active player is found ---
        max_attempts = self.player_count  # Prevent infinite loop if all players are inactive

        for _ in range(max_attempts):
            player_data = self.players[self.current_player_index % self.player_count]
            if player_data.get('is_spy_active', True): # is_spy_active is True for Locals and active Spies
                break # Found an active player

            # Player is inactive (caught Spy or wrongly accused Local), skip their turn
            self.current_player_index += 1
        else:
            # If the loop finishes without finding an active player, the game should already be over
            # (e.g., all players are eliminated). Force a check.
            self.check_win_conditions()
            return

        self.current_player_index = self.current_player_index % self.player_count
        player_data = self.players[self.current_player_index]

        # --- NEW GAME FLOW LOGIC ---

        # 1. Determine random direction
        direction = random.choice(["CLOCKWISE", "COUNTER-CLOCKWISE"])

        # 2. Update UI for new round start
        self.lbl_game_status.text = (
            f"[b]Round Starts With:[/b] [color={TEXT_COLOR_TAG}]{player_data['name']}[/color]"
        )

        self.lbl_turn_instruction.text = (
            f"[b]Round Direction: {direction}[/b]\n\n"
            f"Pass to {direction}. Everyone says one word. Accuse when ready."
        )

        # Manually trigger the width calculation on the instruction label
        if self.lbl_turn_instruction.width > 0:
            self.lbl_turn_instruction.text_size = (self.lbl_turn_instruction.width * 0.95, None)

        # 3. Ensure check role and accuse buttons are enabled/visible for continuous play
        self.btn_check_role.disabled = False
        self.btn_check_role.text = "CHECK YOUR ROLE / SECRET WORD"
        self.btn_check_role.background_color = ACCENT_BLUE

        self.btn_accuse.size_hint_x = 1.0
        self.btn_accuse.disabled = False
        self.btn_accuse.background_color = ACCENT_RED

        # Set screen back to game screen (needed if coming from role assignment)
        self.sm.current = 'game_play'

        # This setup serves as the neutral screen before each turn
        # This text is general and does not reveal the role.
        self.lbl_pass_device.text = (
            f"[b]IT IS NOW YOUR TURN![/b]\n"
            f"[color={TEXT_COLOR_TAG}][size=36sp]{self.current_player_name}[/size][/color]"
        )
        self.lbl_player_info.text = "Tap 'Finished Viewing - Hide Role' to start your turn in the game."

    def next_turn(self, instance=None):
        # This function is ONLY used by EASY/HARD modes
        if self.game_mode == "SINGLE_ROUND":
            # Prevent next_turn from running if accidentally triggered in SR mode
            return

        # Advance the index BEFORE calling update_game_screen
        self.current_player_index = (self.current_player_index + 1) % self.player_count

        self.update_game_screen()

    def show_accuse_popup(self, instance):
        # This function is ONLY used by EASY/HARD modes
        if self.game_mode == "SINGLE_ROUND":
            self.show_single_round_accusation_popup()
            return

        # BoxLayout does not support background_color property
        content = BoxLayout(orientation='vertical', padding=dp(20), spacing=dp(20))
        content.canvas.before.add(kivy.graphics.Color(*LIGHT_BG))
        content.canvas.before.add(kivy.graphics.Rectangle(size=content.size, pos=content.pos))

        content.add_widget(self.wrap_label(text="WHO DO YOU ACCUSE OF BEING THE SPY?", size_hint_y=None, color=TEXT_PRIMARY, font_size='18sp'))

        # --- Scrollable Player List Setup ---

        # 1. Inner BoxLayout for dynamic buttons (Height set dynamically)
        player_list_container = BoxLayout(orientation='vertical', spacing=dp(5), size_hint_y=None)

        # 2. Add buttons for active players
        active_players = [p for p in self.players if p.get('is_spy_active', True)]
        # Set height based on number of active players for scrolling
        player_list_container.height = len(active_players) * (dp(55)) # 50 height + 5 spacing

        for i, player in enumerate(self.players):
            if player.get('is_spy_active', True): # Only list active players for accusation
                # Find original index for resolution
                original_index = self.players.index(player)

                btn = Button(
                    text=player['name'],
                    on_press=lambda x, p_index=original_index: self.resolve_accusation(p_index, popup),
                    size_hint_y=None, height=dp(50), background_color=ACCENT_RED
                )
                player_list_container.add_widget(btn)

        # 3. ScrollView to wrap the inner BoxLayout
        scroll_view = ScrollView(size_hint_y=0.6, do_scroll_x=False)
        scroll_view.add_widget(player_list_container)

        content.add_widget(scroll_view) # Add scrollable area to pop-up content
        # --- END Player List Setup ---

        btn_cancel = self.wrap_button(text="CANCEL ACCUSATION (Resume Game)", on_press=lambda x: self.resume_game(popup), background_color=ACCENT_GREEN, size_hint_y=0.2, height=dp(60))
        content.add_widget(btn_cancel)

        popup = Popup(title='VOTE!', content=content, size_hint=(0.8, 0.9))
        popup.open()

    def check_win_conditions(self):
        # This function is ONLY used by EASY/HARD modes
        if self.game_mode == "SINGLE_ROUND":
            return False # SR mode uses resolve_single_round_accusation

        # Correctly count active spies and locals currently in the game
        active_spies = sum(1 for p in self.players if p['is_spy'] and p.get('is_spy_active', True))
        active_locals = sum(1 for p in self.players if not p['is_spy'] and p.get('is_spy_active', True))

        if active_spies == 0:
            result_text = "ALL SPIES CAUGHT! The Locals successfully neutralized the threat.\n\nLocals Win!"
            self.show_result_popup("Locals", result_text)
            return True

        if active_spies >= active_locals:
            result_text = f"PARITY REACHED! ({active_spies} Spies vs {active_locals} Locals).\n\nThe Spies have outlasted the Locals' attempts to accuse them.\n\nSpies Win!"
            self.show_result_popup("Spy", result_text)
            return True

        return False

    def resolve_accusation(self, accused_index, popup):
        # This function is ONLY used by EASY/HARD modes
        if self.game_mode == "SINGLE_ROUND":
            # Fallback prevention
            popup.dismiss()
            self.resolve_single_round_accusation()
            return

        popup.dismiss()

        accused_player = self.players[accused_index]
        hidden_word_text = "[color=ff5555]???[/color]"

        is_accused_spy = accused_player.get('is_spy_active', True) and accused_player['is_spy'] # Is this an *active* Spy?

        if is_accused_spy:
            # --- CASE 1: Correct Accusation (Spy is caught) ---

            # Save the current active spy count BEFORE elimination
            active_spies_before_elim = sum(1 for p in self.players if p['is_spy'] and p.get('is_spy_active', True))

            accused_player['is_spy_active'] = False # Mark as revealed/caught

            # Calculate remaining spies *after* this elimination
            active_spies_after_elim = active_spies_before_elim - 1

            # NEW LOGIC: Check for Easy Mode guess chance (ANY caught Spy in Easy Mode gets a chance)
            if self.game_mode == "EASY":
                # Any caught Spy in Easy Mode gets a final guess chance
                self.show_spy_guess_popup(accused_player)
                return # Stop all further processing, wait for guess resolution

            # Hard Mode: Check for automatic win/loss conditions
            if self.check_win_conditions():
                return

            # If we reach here, it means other spies remain or it's Hard Mode. Display elimination message.
            active_spies = active_spies_after_elim # Use the already calculated count

            content = BoxLayout(orientation='vertical', padding=dp(20), spacing=dp(20))
            content.canvas.before.add(kivy.graphics.Color(*LIGHT_BG))
            content.canvas.before.add(kivy.graphics.Rectangle(size=content.size, pos=content.pos))

            content.add_widget(
                Label(
                    text=f"[b]Spy ({accused_player['name']}) ELIMINATED![/b]",
                    markup=True,
                    size_hint_y=0.2,
                    color=ACCENT_RED)
                )
            content.add_widget(
                Label(
                    text=(
                        f"The Spy failed to guess the word ({hidden_word_text}) and is now removed from play.\n\n"
                        f"Status: {active_spies} Spies remain. The game continues."
                        ),
                    markup=True,
                    size_hint_y=0.5,
                    color=TEXT_PRIMARY,
                    text_size=(dp(280), None),
                    halign='center',
                    valign='top')
                    )

            btn_continue = self.wrap_button(
                text="CONTINUE GAME",
                size_hint_y=0.2,
                height=dp(60),
                on_press=lambda x: (popup.dismiss(), self.start_next_round()),
                background_color=ACCENT_GREEN
                )
            content.add_widget(btn_continue)

            popup = Popup(title=f'SPY ELIMINATED ({self.game_mode} MODE)', content=content, size_hint=(0.9, 0.7))
            popup.open()

        else:
            # --- CASE 2: Wrong Accusation (Local is caught, or inactive Spy was targeted) ---

            # Mark the player as inactive (effectively eliminated)
            accused_player['is_spy_active'] = False

            # Check if this mistake leads to a Spy victory (parity)
            if self.check_win_conditions():
                return
            else:
                # Game continues.

                # We need to recalculate remaining locals for the message
                active_spies = sum(1 for p in self.players if p['is_spy'] and p.get('is_spy_active', True))
                remaining_locals = sum(1 for p in self.players if not p['is_spy'] and p.get('is_spy_active', True))

                self.resume_game_after_wrong_accusation(accused_player, remaining_locals)

    def resume_game_after_wrong_accusation(self, wrongly_accused_player, remaining_locals):
        # This function is ONLY used by EASY/HARD modes

        # The calculation below was WRONG. It needs to count ACTIVE SPIES, not all active players.
        active_spies = sum(1 for p in self.players if p['is_spy'] and p.get('is_spy_active', True))

        content = BoxLayout(orientation='vertical', padding=dp(20), spacing=dp(20))
        content.canvas.before.add(kivy.graphics.Color(*LIGHT_BG))
        content.canvas.before.add(kivy.graphics.Rectangle(size=content.size, pos=content.pos))

        content.add_widget(Label(text=f"[b]Accusation Failed![/b]", markup=True, size_hint_y=0.2, color=ACCENT_RED))
        content.add_widget(self.wrap_label(
            text=(
                f"You wrongly accused {wrongly_accused_player['name']} (Local). They are now removed from play.\n"
                f"Status: {active_spies} Spies remain vs {remaining_locals} Locals. The game continues."
            ),
            markup=True, size_hint_y=0.5, color=TEXT_PRIMARY,
            text_size=(dp(280), None),
            halign='center', valign='top'
        ))

        btn_continue = self.wrap_button(
            text="CONTINUE GAME",
            size_hint_y=0.2,
            height=dp(60),
            on_press=lambda x: (popup.dismiss(), self.start_next_round()),
            background_color=ACCENT_GREEN
            )
        content.add_widget(btn_continue)

        popup = Popup(title='WRONG ACCUSATION', content=content, size_hint=(0.9, 0.7))
        popup.open()


    def wrap_label(self,
               text,
               color=TEXT_PRIMARY,
               size_hint_y=None,
               size_hint_x=1,
               height=None,
               font_size='16sp',
               halign='center',
               valign='middle',
               markup=True):

        lbl = Label(
            text=text,
            markup=markup,
            color=color,
            halign=halign,
            valign=valign,
            font_size=font_size,
            size_hint_x=size_hint_x,
            size_hint_y=size_hint_y,
            text_size=(0, None)
        )

        def _update_label_size(instance, width):
            # Dynamically set text_size to enable wrapping and recalculate height
            instance.text_size = (width * 0.98, None)
            instance.texture_update()
            instance.height = instance.texture_size[1] + dp(10)
            instance.halign = halign
            instance.valign = valign

        # Bind to width change for dynamic wrapping and to texture_size for height auto-adjustment
        lbl.bind(width=_update_label_size)
        lbl.bind(texture_size=lambda s, ts: setattr(s, 'height', ts[1] + dp(10)))

        # Initial sizing for immediate rendering
        lbl.text_size = (Window.width * 0.8, None)
        lbl.halign = halign
        lbl.valign = valign

        return lbl



    def wrap_button(self, text, background_color=None, size_hint_y=None, height=None, on_press=None, font_size='16sp'):
        final_height = height if height is not None else dp(44)

        btn = Button(
            text=text,
            background_color=background_color or ACCENT_BLUE,
            size_hint_y=size_hint_y,
            height=final_height,
            halign='center',
            valign='middle',
            font_size=font_size,
            text_size=(Window.width * 0.8, None)
        )
        btn.bind(
            width=lambda s, w: setattr(s, 'text_size', (w * 0.9, None))
        )
        btn.bind(texture_size=lambda s, ts: setattr(s, 'height', ts[1] + dp(20)))
        if on_press:
            btn.bind(on_press=on_press)
        return btn


    # --- Spy only guesses after being accused (EASY MODE ONLY) ---
    def show_spy_guess_popup(self, accused_player):
        # Called when any Spy is caught in Easy Mode.

        # If the Spy was successfully accused, stop the timer permanently
        if self.timer_event: self.timer_event.cancel()

        content = BoxLayout(orientation='vertical', padding=dp(20), spacing=dp(15))
        content.canvas.before.add(kivy.graphics.Color(*LIGHT_BG))
        content.canvas.before.add(kivy.graphics.Rectangle(size=content.size, pos=content.pos))

        content.add_widget(self.wrap_label(text=f"SPY ({accused_player['name']}): YOU WERE CAUGHT! GUESS THE WORD FOR A FINAL WIN.", size_hint_y=None, font_size='18sp', color=ACCENT_RED))

        # --- CRITICAL FIX: Only use words from the current category (plus a few decoys) ---

        current_category_words = list(GAME_TOPICS[self.current_category])

        # 1. Get the correct word and remove it from the list of options
        correct_word = self.secret_word
        if correct_word in current_category_words:
            current_category_words.remove(correct_word)

        # 2. Get a small pool of decoys from the current category (max 4)
        num_decoys = min(4, len(current_category_words))
        category_decoys = random.sample(current_category_words, k=num_decoys)

        # 3. Get a few decoys from *other* categories for elimination challenge (max 1 or 2)
        other_category_words = []
        for cat, words in GAME_TOPICS.items():
            if cat != self.current_category:
                other_category_words.extend(words)

        # Ensure we don't pick too many outside decoys
        num_outside_decoys = min(2, len(other_category_words))
        outside_decoys = random.sample(other_category_words, k=num_outside_decoys)

        # Combine all options
        guess_options = set(category_decoys + outside_decoys)
        guess_options.add(correct_word)
        guess_options = list(guess_options)
        random.shuffle(guess_options)

        # --- END CRITICAL FIX ---


        for word in guess_options:
            btn = Button(
                text=word,
                on_press=lambda x, guessed_word=word: self.resolve_spy_guess(guessed_word, popup, accused_player),
                size_hint_y=None, height=dp(50), background_color=(0.3, 0.6, 0.9, 1)
            )
            content.add_widget(btn)

        popup = Popup(title=f"SPY'S LAST CHANCE (Category: {self.current_category})", content=content, size_hint=(0.8, 0.9))
        popup.open()

    def resolve_spy_guess(self, guessed_word, popup, accused_player):
        popup.dismiss()

        if guessed_word == self.secret_word:
            # SPY WINS! (Regardless of whether they were the last spy)
            result_text = f"UNBELIEVABLE! The Spy ({accused_player['name']}) correctly guessed the word: [b]{self.secret_word}[/b]!\n\nSpy Wins!"
            winner = "Spy"
            self.show_result_popup(winner, result_text)
        else:
            # Spy failed the guess. Since this spy is already marked inactive, the game continues.

            # Check win condition immediately after failure
            if self.check_win_conditions():
                return
            else:
                # Spies remain. Game continues.
                active_spies = sum(1 for p in self.players if p['is_spy'] and p.get('is_spy_active', True))

                content = BoxLayout(orientation='vertical', padding=dp(20), spacing=dp(20))
                content.canvas.before.add(kivy.graphics.Color(*LIGHT_BG))
                content.canvas.before.add(kivy.graphics.Rectangle(size=content.size, pos=content.pos))

                content.add_widget(Label(text=f"[b]Spy ({accused_player['name']}) Failed Guess![/b]", markup=True, size_hint_y=0.2, color=ACCENT_RED))

                hidden_word_text = "[color=ff5555]???[/color]"

                content.add_widget(Label(
                    text=(
                        f"The Spy failed to guess the word ({hidden_word_text}) and is now removed from play.\n\n"
                        f"Status: {active_spies} Spies remain. The game continues."
                        ),
                    markup=True, size_hint_y=0.5, color=TEXT_PRIMARY,
                    text_size=(dp(280), None),
                    halign='center', valign='top'
                    ))

                btn_continue = self.wrap_button(text="CONTINUE GAME", size_hint_y=0.2, height=dp(60), on_press=lambda x: self.resume_game(popup), background_color=ACCENT_GREEN)
                content.add_widget(btn_continue)

                popup = Popup(title='SPY REMOVED', content=content, size_hint=(0.9, 0.7))
                popup.open()

    def resume_game(self, popup):
        popup.dismiss()

        self.update_game_screen() # This will ensure the screen transitions correctly
        self.sm.current = 'game_play'

    def start_next_round(self):
        # This function is ONLY used by EASY/HARD modes

        # 1. Reset current player index to *an* active player
        active_player_indices = [i for i, p in enumerate(self.players) if p.get('is_spy_active', True)]

        if not active_player_indices:
            # Should not happen if check_win_conditions was called correctly
            self.check_win_conditions()
            return

        # Randomly select the next round starter from *any* active player
        # No skewing here.
        start_idx = random.choice(active_player_indices)
        self.current_player_index = start_idx # Set the starting player index for the new round

        # 2. Update the game screen with the new starter/direction
        self.update_game_screen()

    def show_result_popup(self, winner, text):
        # FIX: BoxLayout does not support background_color property
        content = BoxLayout(orientation='vertical', padding=dp(20), spacing=dp(20))
        content.canvas.before.add(kivy.graphics.Color(*LIGHT_BG))
        content.canvas.before.add(kivy.graphics.Rectangle(size=content.size, pos=content.pos))

        # NEW: Use conditional color for winner text
        color = '55ff55' if winner == 'Locals' else 'ff5555'
        content.add_widget(Label(text=f"[b][size=40sp][color={color}]{winner.upper()} WIN![/color][/size][/b]", markup=True, size_hint_y=0.3, color=TEXT_PRIMARY))

        content.add_widget(self.wrap_label(
            text=text,
            markup=True,
            size_hint_y=0.4,
            font_size='18sp',
            color=TEXT_PRIMARY,
            halign='center',
            valign='middle'
        ))

        # PRESERVE STATE: The change is here
        btn_new_game = self.wrap_button(text="START REMATCH (Same Players)", size_hint_y=0.2, height=dp(60), on_press=lambda x: self.reset_game(popup, preserve_config=True), background_color=ACCENT_GREEN)
        content.add_widget(btn_new_game)

        # Popup does not support background_color property
        popup = Popup(title='GAME OVER', content=content, size_hint=(0.9, 0.7))
        popup.open()

    def check_word_pool_status(self):
        low_pool_categories = []
        MIN_WORDS_THRESHOLD = 5 # Changed threshold from 10 to 5

        for cat in self.selected_categories:
            if cat not in GAME_TOPICS:
                continue # Skip if category was deleted somehow

            # Calculate remaining words
            used_count = len(self.total_used_words.get(cat, set()))
            total_count = len(GAME_TOPICS[cat])
            available_count = total_count - used_count

            if available_count < MIN_WORDS_THRESHOLD:
                # Calculate how many words are available before reset
                low_pool_categories.append((cat, available_count, total_count))

        if low_pool_categories:
            self.show_low_pool_warning(low_pool_categories)

    def show_low_pool_warning(self, low_pool_categories):
        content = BoxLayout(orientation='vertical', padding=dp(20), spacing=dp(10))
        content.canvas.before.add(Color(*LIGHT_BG))
        content.canvas.before.add(Rectangle(size=content.size, pos=content.pos))

        warning_text = "[b]LOW WORD COUNT WARNING[/b]\n"
        warning_text += "The following categories are running low on unique words:\n\n"

        for cat, available, total in low_pool_categories:
            warning_text += f"- [b]{cat}[/b]: {available} words left.\n"

        warning_text += "\n[i]Regenerate them via Gemini to ensure maximum replayability![/i]"

        # Scrollable area for the list of categories
        warning_label = self.wrap_label(
            text=warning_text,
            color=TEXT_PRIMARY,
            font_size='16sp',
            valign='top',
            size_hint_y=None
        )
        content.add_widget(warning_label)

        control_layout = BoxLayout(size_hint_y=None, height=dp(60), spacing=dp(10))

        btn_regen = self.wrap_button(
            text="REGENERATE TOPICS",
            background_color=ACCENT_BLUE,
            on_press=lambda x: (warning_popup.dismiss(), self.show_regenerate_popup())
        )
        btn_ignore = self.wrap_button(
            text="CONTINUE GAME (IGNORE)",
            background_color=ACCENT_GREEN,
            on_press=lambda x: warning_popup.dismiss()
        )

        control_layout.add_widget(btn_regen)
        control_layout.add_widget(btn_ignore)
        content.add_widget(control_layout)

        warning_popup = Popup(title='WORD POOL DEPLETED!', content=content, size_hint=(0.9, 0.7))
        warning_popup.open()

    def reset_game(self, popup, preserve_config=False):
        if popup:
            popup.dismiss()

        # --- Round-specific resets ---
        self.game_state = "SETUP"
        self.current_category = ""
        self.secret_word = ""
        self.is_current_player_spy = False
        self.current_player_index = 0
        self.role_reveal_order = []
        self.gemini_status = ""
        self.single_round_accusations = set() # Reset SR tracker

        # --- Config Preservation ---
        if not preserve_config:
            # Only reset player/spy counts and game mode if we aren't preserving the config
            self.player_count = 3
            self.spy_count = 1
            self.game_mode = "EASY"
            self.player_names_list = [f"Player {i+1}" for i in range(10)]
            self.players = []

            self.total_used_words = {cat: set() for cat in GAME_TOPICS.keys()}

        # Update UI elements that may have changed
        self.lbl_count.text = str(self.player_count)
        self.lbl_spy_count.text = str(self.spy_count)

        # Update mode button colors
        self.btn_easy_mode.background_color = ACCENT_GREEN if self.game_mode == "EASY" else LIGHT_BG
        self.btn_hard_mode.background_color = ACCENT_RED if self.game_mode == "HARD" else LIGHT_BG
        self.btn_single_mode.background_color = ACCENT_YELLOW if self.game_mode == "SINGLE_ROUND" else LIGHT_BG

        self.check_word_pool_status()

        self.sm.current = 'setup'

    # --- Gemini Generation Methods ---
    def show_regenerate_popup(self):
        content = BoxLayout(orientation='vertical', padding=dp(20), spacing=dp(15))
        content.canvas.before.add(kivy.graphics.Color(*LIGHT_BG))
        content.canvas.before.add(kivy.graphics.Rectangle(size=content.size, pos=content.pos))

        content.add_widget(self.wrap_label(text="Select a category to regenerate via Gemini:", color=TEXT_PRIMARY, size_hint_y=None, height=dp(60)))

        for cat in GAME_TOPICS.keys():
            btn = Button(text=f"Regenerate '{cat}'", size_hint_y=None, height=dp(50),
                        background_color=ACCENT_BLUE,
                        on_press=lambda x, c=cat: (popup.dismiss(), self.trigger_gemini_generation(c, popup)))
            content.add_widget(btn)

        popup = Popup(title='Regenerate Existing Category', content=content, size_hint=(0.9, 0.8))
        popup.open()

    def show_generation_popup(self, instance):
        self.gemini_status = ""
        self.lbl_gemini_status.text = "[color=808080]Enter a category and hit 'Query Gemini'.[/color]"

        # FIX: BoxLayout does not support background_color property
        popup_content = BoxLayout(orientation='vertical', padding=dp(20), spacing=dp(15))
        popup_content.canvas.before.add(kivy.graphics.Color(*LIGHT_BG))
        popup_content.canvas.before.add(kivy.graphics.Rectangle(size=popup_content.size, pos=popup_content.pos))

        popup_content.add_widget(self.wrap_label(text="Enter a New Topic Category Name (e.g., 'Space', 'Fantasy'):", size_hint_y=None, height=dp(60), color=TEXT_PRIMARY))

        self.ti_category_name = TextInput(
            text="",
            multiline=False,
            size_hint_y=None,
            height=dp(50),
            hint_text="New Category Name",
            foreground_color=TEXT_PRIMARY,
            background_color=(0.2, 0.2, 0.2, 1)
        )
        popup_content.add_widget(self.ti_category_name)

        btn_generate = self.wrap_button(
            text="QUERY GEMINI FOR 10 NEW WORDS",
            size_hint_y=None, height=dp(60),
            on_press=lambda x: self.trigger_gemini_generation(self.ti_category_name.text, popup),
            background_color=ACCENT_BLUE
        )
        popup_content.add_widget(btn_generate)

        # FIX: Popup does not support background_color property
        popup = Popup(
            title='AI TOPIC GENERATOR',
            content=popup_content,
            size_hint=(0.9, 0.6)
        )
        popup.open()

    def get_gemini_api_url(self):
        """Returns the fully formed API URL using the current session key."""
        # Use GEMINI_MODEL defined globally
        return f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent?key={self.session_api_key}"

    def trigger_gemini_generation(self, category_name, popup):
        if not category_name.strip():
            self.gemini_status = "Error: Please enter a category name."
            self.lbl_gemini_status.text = f"[color=ff0000]{self.gemini_status}[/color]"
            return

        popup.dismiss()
        self.gemini_status = f"[b]Querying Gemini for '{category_name}'...[/b]"
        self.lbl_gemini_status.text = f"[color=8080ff]{self.gemini_status}[/color]"

        # Start the network request in a separate thread
        threading.Thread(
            target=self.call_gemini_api,
            args=(category_name,)
        ).start()

    def call_gemini_api(self, category_name):
        # This runs in a separate thread and MUST NOT interact with the UI directly

        system_prompt = (
            "You are a creative word generator for a party game similar to Spyfall. "
            "Your task is to generate secret words or locations for the given category. "
            "The words must be concrete, specific proper nouns or well-known fixed entities/locations, "
            "and vague enough to allow conversation without obvious giveaways. "
            "Do not use generic locations like 'school' or 'beach'."
        )
        user_query = f"Generate 10 unique, creative, and plausible secret proper nouns or fixed entities for the category: '{category_name}'. The items must be single concepts or short phrases (max 4 words)."

        payload = {
            "contents": [{ "parts": [{ "text": user_query }] }],
            "systemInstruction": { "parts": [{ "text": system_prompt }] },
            "generationConfig": {
                "responseMimeType": "application/json",
                "responseSchema": {
                    "type": "OBJECT",
                    "properties": {
                        "words": {
                            "type": "ARRAY",
                            "description": "A list of 10 unique words or short phrases for the category.",
                            "items": { "type": "STRING" }
                        }
                    }
                }
            }
        }

        max_retries = 3
        delay = 1
        response_data = None

        if not self.session_api_key:
            # Schedule the error handler immediately
            Clock.schedule_once(lambda dt: self.handle_gemini_result(category_name, None, "No API Key Provided."), 0)
            return

        for attempt in range(max_retries):
            try:
                response = requests.post(
                    self.get_gemini_api_url(),
                    headers={'Content-Type': 'application/json'},
                    data=json.dumps(payload),
                    timeout=15
                )
                response.raise_for_status()
                response_data = response.json()
                break
            except requests.exceptions.RequestException:
                if attempt < max_retries - 1:
                    threading.Event().wait(delay)
                    delay *= 2
                else:
                    Clock.schedule_once(lambda dt: self.handle_gemini_result(category_name, None, "Network or API failure."), 0)
                    return

        Clock.schedule_once(lambda dt: self.handle_gemini_result(category_name, response_data), 0)

    def handle_gemini_result(self, category_name, response_data, error=None):
        # This function runs back on the main Kivy thread

        if error:
            self.gemini_status = f"[b]ERROR:[/b] Failed to query AI: {error}"
            self.lbl_gemini_status.text = f"[color=ff0000]{self.gemini_status}[/color]"
            return

        try:
            json_text = response_data['candidates'][0]['content']['parts'][0]['text']
            parsed_json = json.loads(json_text)
            new_words = parsed_json.get('words', [])

            if new_words:
                # Add the new words to the session's topic pool (Temporarily before confirmation)
                # We will only permanently save them if the user accepts.
                temp_topic_pool = GAME_TOPICS.copy()
                temp_topic_pool[category_name] = new_words

                # Update status and show review
                self.gemini_status = f"[b]WORDS GENERATED![/b] Review below."
                self.lbl_gemini_status.text = f"[color=8080ff]{self.gemini_status}[/color]"

                content = BoxLayout(orientation='vertical', padding=dp(20), spacing=dp(20))
                content.canvas.before.add(kivy.graphics.Color(*LIGHT_BG))
                content.canvas.before.add(kivy.graphics.Rectangle(size=content.size, pos=content.pos))

                review_text = f"Category: [b]{category_name}[/b]\n\n"
                review_text += "Review words for appropriateness before playing:\n" + "\n".join(new_words)

                # ... (content creation) ...
                content.add_widget(Label(text="[b]NEW WORDS GENERATED[/b]", markup=True, size_hint_y=0.2, color=TEXT_PRIMARY))

                # Use ScrollView for review text in case there are many words
                review_scroll = ScrollView(size_hint_y=0.6)
                review_label = Label(text=review_text, markup=True, font_size='14sp', valign='top', halign='left', color=TEXT_SECONDARY, text_size=(dp(280), None))
                review_label.bind(texture_size=review_label.setter('size'))
                review_scroll.add_widget(review_label)
                content.add_widget(review_scroll)

                # Button Control Layout
                control_layout = BoxLayout(size_hint_y=0.2, spacing=dp(10))

                # NEW: Accept Button
                btn_accept = self.wrap_button(
                    text="ACCEPT & ADD TOPIC",
                    background_color=ACCENT_GREEN,
                    height=dp(50),
                    on_press=lambda x: self.finalize_new_topic(category_name, new_words, review_popup, accepted=True))
                # NEW: Reject Button
                btn_reject = self.wrap_button(
                    text="REJECT & DISCARD",
                    background_color=ACCENT_RED,
                    height=dp(50),
                    on_press=lambda x: self.finalize_new_topic(category_name, new_words, review_popup, accepted=False))

                control_layout.add_widget(btn_reject)
                control_layout.add_widget(btn_accept)
                content.add_widget(control_layout)

                review_popup = Popup(title='CONTENT REVIEW', content=content, size_hint=(0.9, 0.8))
                review_popup.open()

            else:
                self.gemini_status = "[b]ERROR:[/b] AI returned empty list of words."
                self.lbl_gemini_status.text = f"[color=ff0000]{self.gemini_status}[/color]"

        except (KeyError, json.JSONDecodeError, IndexError) as e:
            self.gemini_status = f"[b]ERROR:[/b] Failed to parse AI response."
            self.lbl_gemini_status.text = f"[color=ff0000]{self.gemini_status}[/color]"

    def finalize_new_topic(self, category_name, new_words, popup, accepted):
        popup.dismiss()

        if accepted:
            global GAME_TOPICS
            GAME_TOPICS[category_name] = new_words
            self.total_used_words[category_name] = set()
            if category_name not in self.selected_categories:
                 self.selected_categories.append(category_name)
            self.save_topics_to_store()

            self.gemini_status = f"[b]SUCCESS![/b] New category '{category_name}' added ({len(new_words)} words)."
            color_tag = "00cc00"
        else:
            self.gemini_status = f"[b]DISCARDED![/b] Category '{category_name}' discarded."
            color_tag = "ff0000"

        self.lbl_gemini_status.text = (
            f"[color={color_tag}]{self.gemini_status}[/color]\n"
            f"[color=808080]Available Categories:[/color] " + ", ".join(GAME_TOPICS.keys())
        )

    def save_topics_to_store(self):
        """Saves the current state of GAME_TOPICS to JsonStore."""
        global GAME_TOPICS

        self.store.put('topics', topics=GAME_TOPICS)

class SpyfallApp(App):
    def build(self):
        Window.clearcolor = DARK_BG
        self.title = "Word Spyfall AI Edition"
        return SpyGame()

if __name__ == '__main__':
    # Add dependency imports for Kivy graphics after App class definition
    import kivy.graphics
    SpyfallApp().run()
