from flask import Flask

app = Flask(__name__)

@app.route('/')
def home():
    return """
    <div style="font-family: Arial; text-align: center; margin-top: 100px;">
        <h1 style="color: #ff9900;">Hello from Amazon ECS!</h1>
        <p style="font-size: 18px;">This Python Flask application is running inside a <b>Docker Container</b>!</p>
        <p style="font-size: 16px; color: green;">Powered by AWS Fargate (Serverless Compute for Containers)</p>
    </div>
    """

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
