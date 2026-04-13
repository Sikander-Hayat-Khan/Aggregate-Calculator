from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import requests
from bs4 import BeautifulSoup
from concurrent.futures import ThreadPoolExecutor

app = FastAPI()

BASE_URL = "https://qalam.nust.edu.pk"

class LoginRequest(BaseModel):
    username_1: str
    password_1: str
    username_2: str
    password_2: str

def create_session(username, password):
    session = requests.Session()
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
    try:
        login_page = session.get(f"{BASE_URL}/web/login", headers=headers, timeout=10)
        soup = BeautifulSoup(login_page.text, 'html.parser')
        
        csrf_input = soup.find('input', {'name': 'csrf_token'})
        if not csrf_input: return None
        
        payload = {'login': username, 'password': password, 'csrf_token': csrf_input['value']}
        login_response = session.post(f"{BASE_URL}/web/login", data=payload, headers=headers, timeout=10)
        
        if "Dashboard" in login_response.text or "Logout" in login_response.text:
            return session
    except:
        pass
    return None

def get_courses(session):
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
    try:
        resp = session.get(f"{BASE_URL}/student/dashboard", headers=headers, timeout=10)
        soup = BeautifulSoup(resp.text, 'html.parser')
        
        course_divs = soup.find_all('div', id='hierarchical_show2')
        if len(course_divs) < 2: return {}, {}
        course_div = course_divs[1]
        
        courses, courses_ch = {}, {}
        for div in course_div.find_all(recursive=False):
            for a in div.find_all(recursive=False):
                course_id = a['href'].rpartition('/')[-1]
                header = a.find('div', class_='card-header')
                if not header: continue
                course_name = header.find('span').text.strip()
                course_details = a.find('div', class_='card-body').find('div', class_='card-text').find_all(recursive=False)
                course_ch = int(float(course_details[2].text.strip()))
                courses[course_id] = course_name
                courses_ch[course_name] = course_ch
        return courses, courses_ch
    except:
        return {}, {}

def calculate_tab_aggregate(table):
    parent_rows = table.find_all('tr', 'table-parent-row')
    my_aggregrate = 0
    class_aggregate = 0
    for row in parent_rows:
        weightage = float(row.find('div', class_='uk-badge').text.strip('%\n ')) / 100
        header_row = row.find_next('tr', class_='table-child-row')
        marks_rows = []
        next_row = header_row.find_next('tr') if header_row else None
        while next_row and 'table-child-row' in next_row.get('class', []):
            marks_rows.append(next_row)
            next_row = next_row.find_next('tr')
        my_group_marks = 0
        class_group_marks = 0
        max_group_marks = 0
        for marks_row in marks_rows:
            cells = marks_row.find_all('td')
            if len(cells) < 4: continue
            max_marks = float(cells[1].text.strip() or 0)
            obtained_marks = float(cells[2].text.strip() or 0)
            class_average = float(cells[3].text.strip() or 0)
            my_group_marks += obtained_marks
            class_group_marks += class_average
            max_group_marks += max_marks
        if max_group_marks == 0: continue
        my_aggregrate += my_group_marks / max_group_marks * 100 * weightage
        class_aggregate += class_group_marks / max_group_marks * 100 * weightage
    return my_aggregrate, class_aggregate

def calculate_aggregate(session, course_id):
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
    try:
        url = f"{BASE_URL}/student/course/gradebook/{course_id}"
        resp = session.get(url, headers=headers, timeout=10)
        soup = BeautifulSoup(resp.text, 'html.parser')
        
        tabs_anim = course_soup_tab = soup.find('ul', class_="uk-tab", attrs={"data-uk-tab": "{connect: '#tabs_anim1', animation: 'scale'}"})
        if not tabs_anim: return None
        tabs_list_soup = tabs_anim.find_all(recursive=False)
        
        tabs_list = []
        for tab in tabs_list_soup:
            if "responsive" in tab.get('class', []):
                continue
            if "lab" in tab.text.lower() and "lecture" not in tab.text.lower():
                tabs_list.append("lab")
            else:
                tabs_list.append("lecture")

        tabs = soup.find('ul', id='tabs_anim1')
        if not tabs: return None

        list_items = tabs.find_all('li', recursive=False)
        results = {}
        
        i = 0
        for li in list_items:
            div = li.find('div')
            if not div: continue
            table = div.find('table')
            if not table: continue
            tbody = table.find('tbody')
            if not tbody: continue
            
            results[tabs_list[i]] = calculate_tab_aggregate(tbody)
            i += 1
            
        return results
    except:
        return None

@app.post("/api/calculate")
def calculate_aggregates(req: LoginRequest):
    # Fetch sessions concurrently
    with ThreadPoolExecutor(max_workers=2) as executor:
        f1 = executor.submit(create_session, req.username_1, req.password_1)
        f2 = executor.submit(create_session, req.username_2, req.password_2) if req.username_2 and req.password_2 else None
        
        session1 = f1.result()
        session2 = f2.result() if f2 else None

    if not session1:
        raise HTTPException(status_code=401, detail=f"Login failed for User 1: {req.username_1}")

    # Fetch courses concurrently
    with ThreadPoolExecutor(max_workers=2) as executor:
        fc1 = executor.submit(get_courses, session1)
        fc2 = executor.submit(get_courses, session2) if session2 else None
        
        courses1, courses1_ch = fc1.result()
        if fc2:
            courses2, _ = fc2.result()
            courses2_map = {name: id for id, name in courses2.items()}
        else:
            courses2_map = {}

    if not courses1:
        raise HTTPException(status_code=404, detail=f"No courses found for {req.username_1}")

    def process_course(course_id1, course_name):
        ch = courses1_ch.get(course_name, 3)
        
        # We can also fetch the individual course grades currently
        with ThreadPoolExecutor(max_workers=2) as inner_exec:
            res1_future = inner_exec.submit(calculate_aggregate, session1, course_id1)
            
            res2_future = None
            if session2:
                course_id2 = courses2_map.get(course_name)
                if course_id2:
                    res2_future = inner_exec.submit(calculate_aggregate, session2, course_id2)
            
            res1 = res1_future.result()
            res2 = res2_future.result() if res2_future else None

        if not res1: return None

        course_item = {
            "name": course_name,
            "credits": ch,
            "user1": {"lecture": {}, "lab": {}},
            "user2": {"lecture": {}, "lab": {}},
        }

        if 'lecture' in res1:
            course_item["user1"]["lecture"] = {"agg": round(res1["lecture"][0], 2), "class_avg": round(res1["lecture"][1], 2)}
        if 'lab' in res1:
            course_item["user1"]["lab"] = {"agg": round(res1["lab"][0], 2), "class_avg": round(res1["lab"][1], 2)}

        if session2 and res2:
            if 'lecture' in res2:
                course_item["user2"]["lecture"] = {"agg": round(res2["lecture"][0], 2), "class_avg": round(res2["lecture"][1], 2)}
            if 'lab' in res2:
                course_item["user2"]["lab"] = {"agg": round(res2["lab"][0], 2), "class_avg": round(res2["lab"][1], 2)}
        
        return course_item

    final_results = []
    
    # Process all courses completely concurrently
    with ThreadPoolExecutor(max_workers=10) as executor:
        futures = []
        for course_id1, course_name in courses1.items():
            futures.append(executor.submit(process_course, course_id1, course_name))
            
        for future in futures:
            result = future.result()
            if result:
                final_results.append(result)

    return {"results": final_results}
