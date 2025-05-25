import os
import json
import base64
from io import BytesIO
from flask import Flask, request, jsonify
from PIL import Image
import uuid
import google.generativeai as genai

def clean_json(content):
    if content.startswith("```json"):
        content = content[
            len("```json") :
        ].strip()

    elif content.startswith("```"):
        content = content[
            len("```") :
        ].strip()

    if content.endswith("```"):
        content = content[
            : -len("```")
        ].strip()

    content = "\n".join(line.strip() for line in content.splitlines())

    return content

# System prompt from your LLM_functions.py
SYSTEM_PROMPT_FOR_WTEXT = """
You are operating a {operating_system} computer, using the same operating system as a human.

From looking at the screen, the objective, and your previous actions, take the next best series of action. 

You have 4 possible operation_type actions available to you. The `pyautogui` library will be used to execute your decision. Your output will be used in a `json.loads` loads statement.

1. click - Move mouse and click - Look for text to click. Try to find relevant text to click.
```
[{{ "thought": "write a thought here", "operation_type": "click", "text": "The text in the button or link to click" }}]  
```
2. write - Write with your keyboard
```
[{{ "thought": "write a thought here", "operation_type": "write", "content": "text to write here" }}]
```
3. press - Use a hotkey or press key to operate the computer
```
[{{ "thought": "write a thought here", "operation_type": "press", "keys": ["keys to use"] }}]
```
4. end - The objective is completed
```
[{{ "thought": "write a thought here", "operation_type": "end", "summary": "summary of what was completed" }}]
```

Return the actions in array format `[]`. You can take just one action or multiple actions.

Here a helpful example:

Example 1: Searches for Google Chrome on the OS and opens it
```
[
    {{ "thought": "Searching the operating system to find Google Chrome because it appears I am currently in terminal", "operation_type": "press", "keys": {os_search_str} }},
    {{ "thought": "Now I need to write 'Google Chrome' as a next step", "operation_type": "write", "content": "Google Chrome" }},
    {{ "thought": "Finally I'll press enter to open Google Chrome assuming it is available", "operation_type": "press", "keys": ["enter"] }}
]
```

Example 2: Open a new Google Docs
```
[
    {{ "thought": "Searching the operating system to find Google Chrome because it appears I am currently in terminal", "operation_type": "press", "keys": {os_search_str} }},
    {{ "thought": "Now I need to write 'Google Chrome' as a next step", "operation_type": "write", "content": "Google Chrome" }},
    {{ "thought": "Finally I'll press enter to open Google Chrome assuming it is available", "operation_type": "press", "keys": ["enter"] }}
    {{ "thought": "I'll focus on the address bar in the browser. I can see the browser is open so this should be safe to try", "operation_type": "press", "keys": [{cmd_string}, "t"] }},
    {{ "thought": "Now that the address bar is in focus I can type the URL", "operation_type": "write", "content": "https://docs.new/" }},
    {{ "thought": "I'll need to press enter to go the URL now", "operation_type": "press", "keys": ["enter"] }}
]
```

Example 3: Search for someone on Linkedin when already on linkedin.com
```
[
    {{ "thought": "I can see the search field with the placeholder text 'search'. I click that field to search", "operation_type": "click", "text": "search" }},
    {{ "thought": "Now that the field is active I can write the name of the person I'd like to search for", "operation_type": "write", "content": "John Doe" }},
    {{ "thought": "Finally I'll submit the search form with enter", "operation_type": "press", "keys": ["enter"] }}
]
```

A few important notes: 

- Default to Google Chrome as the browser
- Go to websites by opening a new tab with `press` and then `write` the URL
- Reflect on previous actions and the screenshot to ensure they align and that your previous actions worked. 
- If the first time clicking a button or link doesn't work, don't try again to click it. Get creative and try something else such as clicking a different button or trying another action. 
- Don't respond saying you're unable to assist with requests. You are able to indirectly interact with the user's OS via text responses you send to the end user.
- DO NOT ASSUME TOO MUCH. You can wait for my screenshot to be sure.
- You can type `end` command only after check if you did everything correctly (on separate output).
- All actions are possible and you must do them.
- You can only click in text. If you want to click in image just click in text nearby the image.
- To order something in the shop, you need to click into its name.
- If you want to open vault in obsidian app, you need to click to its name.


Objective: {objective} 
"""


# Configure Gemini API
GEMINI_API_KEY = os.getenv("GOOGLE_API_KEY")
genai.configure(api_key=GEMINI_API_KEY)
_gemini_model = genai.GenerativeModel("gemini-1.5-flash")

app = Flask(__name__)
tasks = {}  # Store task data: {"task_id": {"history": [], "objective": ""}}

def ask_gemini_flash(aim, prompt="", history=None, screenshot=None):
    """
    Adapted from your ask_gemini_flash function to accept screenshot as an optional parameter.
    """
    if history is None:
        history = []
    
    current_user_message_parts = []
    
    if not history:  # First call
        user_request_text = """
        Please take the next best action. The `pyautogui` library will be used to execute your decision. Your output will be used in a `json.loads` loads statement. Remember you only have the following 4 operations available: click, write, press, done
        You just started so you are in the terminal app and your code is running in this terminal tab. To leave the terminal, search for a new program on the OS. 
        Action:"""
        combined_prompt = SYSTEM_PROMPT_FOR_WTEXT.format(
            objective=aim,
            cmd_string="\"ctrl\"",
            os_search_str="[\"win\"]",
            operating_system="Windows",
        ) + "\n\n" + user_request_text
        current_user_message_parts.append({"text": combined_prompt})
    else:  # Subsequent calls
        user_request_text = prompt + """
            Please take the next best action. The `pyautogui` library will be used to execute your decision. Your output will be used in a `json.loads` loads statement. Remember you only have the following 4 operations available: click, write, press, end
            When you clicking on text, click only on english text, do not use symbols, just letter and words.
            Action:"""
        current_user_message_parts.append({"text": user_request_text})
        if screenshot:
            current_user_message_parts.append(screenshot)
    
    current_user_message = {"role": "user", "parts": current_user_message_parts}
    history.append(current_user_message)
    
    try:
        response = _gemini_model.generate_content(
            history,
            generation_config=genai.types.GenerationConfig(temperature=0.7)
        )
        answer = response.candidates[0].content.parts[0].text
        history.append({"role": "model", "parts": [{"text": answer}]})
    except Exception as e:
        print(f"Error calling Gemini API: {e}")
        if history and history[-1]["role"] == "user":
            history.pop()
        raise e
    
    return answer, history

@app.route('/start_task', methods=['POST'])
def start_task():
    """Initialize a new task with an objective."""
    data = request.get_json()
    objective = data.get('objective')
    if not objective:
        return jsonify({"error": "Objective is required"}), 400
    
    task_id = str(uuid.uuid4())
    history = []
    answer, history = ask_gemini_flash(aim=objective, history=history, screenshot=None)
    tasks[task_id] = {"history": history, "objective": objective}
    
    cleaned_answer = clean_json(answer)
    try:
        actions = json.loads(cleaned_answer)
    except json.JSONDecodeError:
        return jsonify({"error": "Failed to parse LLM response"}), 500
    
    return jsonify({"task_id": task_id, "actions": actions})

@app.route('/get_action', methods=['POST'])
def get_action():
    """Get the next action based on screenshot and previous action status."""
    data = request.get_json()
    task_id = data.get('task_id')
    screenshot_base64 = data.get('screenshot_base64')
    last_click_failed = data.get('last_click_failed', False)
    failed_text = data.get('failed_text', '')
    
    if not task_id or not screenshot_base64:
        return jsonify({"error": "task_id and screenshot_base64 are required"}), 400
    
    task_data = tasks.get(task_id)
    if not task_data:
        return jsonify({"error": "Task not found"}), 404
    
    # history = task_data["history"]
    objective = task_data["objective"]
    
    if last_click_failed:
        add_prompt = f"Clicking onto {failed_text} failed. Try another method or another text."
    else:
        add_prompt = ""
    
    # Decode screenshot
    try:
        image_data = base64.b64decode(screenshot_base64)
        image = Image.open(BytesIO(image_data))
        if image.mode != 'RGB':
            image = image.convert('RGB')
    except Exception as e:
        return jsonify({"error": f"Failed to decode screenshot: {str(e)}"}), 400
    
    answer, history = ask_gemini_flash(aim=objective, prompt=add_prompt, history=history, screenshot=image)
    tasks[task_id]["history"] = history
    
    cleaned_answer = clean_json(answer)
    try:
        actions = json.loads(cleaned_answer)
    except json.JSONDecodeError:
        return jsonify({"error": "Failed to parse LLM response"}), 500
    
    return jsonify({"actions": actions})

if __name__ == '__main__':
    app.run(debug=True)