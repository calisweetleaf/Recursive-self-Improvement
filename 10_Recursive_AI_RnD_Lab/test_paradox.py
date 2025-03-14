import requests
import json

def test_paradox_detection():
    url = "http://localhost:5000/api/check_paradox"
    
    test_cases = [
        {"prompt": "This statement is false", "should_detect": True},
        {"prompt": "Normal statement that isn't paradoxical", "should_detect": False},
        {"prompt": "Am I telling the truth when I say I'm lying", "should_detect": True}
    ]
    
    print("Testing paradox detection...")
    for i, test in enumerate(test_cases):
        try:
            response = requests.post(
                url, 
                json={"prompt": test["prompt"]},
                headers={"Content-Type": "application/json"}
            )
            
            result = response.json()
            expected = test["should_detect"]
            actual = result.get("paradox_detected", False)
            
            print(f"Test {i+1}: {'PASS' if expected == actual else 'FAIL'} - {test['prompt']}")
            if expected == actual and actual == True:
                print(f"  Message: {result.get('message', '')}")
        except Exception as e:
            print(f"Test {i+1}: ERROR - {str(e)}")
        
        print()
        
if __name__ == "__main__":
    test_paradox_detection()