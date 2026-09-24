import sys, time, threading, queue, numpy as np
vfifo, afifo = sys.argv[1], sys.argv[2]
def writer(path, q):
    with open(path, "wb", buffering=0) as f:          # open blocks here, in its own thread, until ffmpeg opens the read end
        while True:
            b = q.get()
            if b is None: return
            f.write(b)
vq, aq = queue.Queue(maxsize=8), queue.Queue(maxsize=8)
threading.Thread(target=writer, args=(vfifo, vq), daemon=True).start()
threading.Thread(target=writer, args=(afifo, aq), daemon=True).start()
H,W=280,440; sr=48000; n=1600
U=np.ones((H,W),np.float32); V=np.zeros((H,W),np.float32); V[130:150,210:230]=0.5
def lap(a): return np.roll(a,1,0)+np.roll(a,-1,0)+np.roll(a,1,1)+np.roll(a,-1,1)-4*a
frame=np.zeros((720,1280,3),np.uint8); tt=np.arange(n)/sr
t0=time.perf_counter(); frames=150; slow=0
for i in range(frames):
    ts=time.perf_counter()
    for _ in range(2):
        uvv=U*V*V; U+=0.16*lap(U)-uvv+0.037*(1-U); V+=0.08*lap(V)+uvv-0.097*V
    img=(np.clip(V*4,0,1)*255).astype(np.uint8)
    frame[:560,:880,0]=np.kron(img,np.ones((2,2),np.uint8)); frame[:560,:880,2]=255-frame[:560,:880,0]
    vq.put(frame.tobytes())
    ph=i*n/sr; sig=np.tanh(sum(np.sin(2*np.pi*f*(tt+ph))*0.2 for f in (110,164.8,220))*1.5)
    aq.put((np.stack([sig,sig],-1)*9000).astype(np.int16).tobytes())
    if time.perf_counter()-ts>1/30: slow+=1
    d=t0+(i+1)/30-time.perf_counter()
    if d>0: time.sleep(d)
vq.put(None); aq.put(None)
while not (vq.empty() and aq.empty()): time.sleep(0.05)
time.sleep(0.5)
sys.stderr.write(f"generator: {frames} frames, {slow} over budget, wall {time.perf_counter()-t0:.2f}s\n")
