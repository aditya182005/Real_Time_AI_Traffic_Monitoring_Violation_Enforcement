import streamlit as st

from app.ui import theme


def render():
    theme.page_head(
        "About",
        "AI-based smart traffic monitoring and automated violation "
        "enforcement. An academic prototype.",
    )

    st.markdown(
        """
### How it works
1. **YOLOv8** finds cars, motorcycles, buses and trucks in every frame, plus
   ambulances, fire trucks and police cars with the custom model.
2. **ByteTrack** gives each vehicle an ID that stays with it across frames.
3. Decision modules read the tracks:
   - **Red light:** a vehicle crosses the stop line while the simulated
     signal is red.
   - **Speeding:** the time a vehicle takes to cross two lines a known
     distance apart.
   - **Wrong way:** a vehicle travels against the expected direction for a
     clear distance.
   - **Collision:** boxes overlap for several frames **and** a vehicle slows
     sharply, so ordinary congestion is not flagged.
   - **Emergency priority:** an emergency vehicle confirmed over several
     frames turns the simulated signal green for a while.
4. Everything is stored in **SQLite** and shown on the Dashboard. Collision
   alerts go out through **Twilio** SMS (and an optional call) when it is
   set up and you turn them on.

### Limits to keep in mind
- There is no real signal hardware. Signal state and priority are simulated.
- Speed is only as accurate as the distance you enter and a fixed camera.
- Collision alerts are heuristic and need a person to verify them.
- Fines are demo amounts, not legal penalties.
        """
    )
