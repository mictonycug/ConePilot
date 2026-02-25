import cv2

cap = cv2.VideoCapture(0)  # try 0, if not working try 1 or 2

if not cap.isOpened():
    print("Could not open camera")
    raise SystemExit

while True:
    ret, frame = cap.read()
    if not ret:
        print("Failed to read frame")
        break

    cv2.imshow("Webcam", frame)

    # press q to quit
    if cv2.waitKey(1) & 0xFF == ord("q"):
        break

cap.release()
cv2.destroyAllWindows()