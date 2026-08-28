"""
Razorpay test-mode connectivity smoke test (Tier 0, step 5).

Confirms RAZORPAY_KEY_ID / RAZORPAY_KEY_SECRET in .env are live and working:
creates a test-mode Order, fetches it back, and exercises the capture call.

Razorpay never exposes a way to create a *completed* payment purely
server-side -- by design, that would bypass PCI-DSS controls, and this
account specifically has neither S2S UPI Collect (POST /payments/create/upi)
nor the generic S2S JSON endpoint (POST /payments/create/json) provisioned
(both return a clean 404, confirmed empirically -- not a payload bug). So a
real payment_id only exists after a customer completes Razorpay's hosted
Checkout, in a real browser. This script does everything a backend can do on
its own (create + fetch the order), and if no --payment-id is given, it
writes a local HTML file that opens Razorpay Checkout against the order it
just created.

Two payment methods are available on that checkout page, both left wired up:
  - UPI (primary demo path -- ties to the NPCI/UPI framing in the track
    brief). Prefilled with Razorpay's test-mode auto-success VPA,
    success@razorpay, and preselected as the default tab, so completing a
    payment is one click: open the file, click Verify, click Pay. No typing,
    no OTP, no waiting on a real UPI app.
  - Card (fallback). Test card 4111 1111 1111 1111, any future expiry, any
    CVV -- currently blocked on this account by an account-level
    restriction ("Business - International Card Not Allowed"), unrelated to
    this code; a support ticket is open with Razorpay in parallel.

Refuses to run against anything that isn't an rzp_test_ key -- this must
never touch a live key.

Usage:
    python scripts/razorpay_smoke.py
    python scripts/razorpay_smoke.py --payment-id pay_xxxxxxxxxxxxx
"""

import argparse
import functools
import http.server
import os
import socketserver
import sys
import tempfile
import threading
import time
import webbrowser
from pathlib import Path

import razorpay
from dotenv import load_dotenv

CHECKOUT_JS_URL = "https://checkout.razorpay.com/v1/checkout.js"
TEST_AMOUNT_PAISE = 100  # INR 1.00
TEST_CURRENCY = "INR"
TEST_UPI_VPA = "success@razorpay"  # Razorpay test-mode VPA: instant simulated success


def get_client() -> tuple[razorpay.Client, str]:
    load_dotenv(override=False)
    key_id = os.environ.get("RAZORPAY_KEY_ID", "").strip()
    key_secret = os.environ.get("RAZORPAY_KEY_SECRET", "").strip()

    if not key_id or not key_secret:
        print("REFUSING: RAZORPAY_KEY_ID / RAZORPAY_KEY_SECRET not set in .env.", file=sys.stderr)
        sys.exit(1)

    if not key_id.startswith("rzp_test_"):
        print(
            f"REFUSING: RAZORPAY_KEY_ID does not start with 'rzp_test_' "
            f"(got prefix {key_id[:9]!r}). This script must never run against a live key.",
            file=sys.stderr,
        )
        sys.exit(1)

    return razorpay.Client(auth=(key_id, key_secret)), key_id


def create_test_order(client: razorpay.Client) -> dict:
    return client.order.create(
        {
            "amount": TEST_AMOUNT_PAISE,
            "currency": TEST_CURRENCY,
            "receipt": f"agentfront-smoke-{int(time.time())}",
            "payment_capture": 0,  # manual capture -- makes the capture call below meaningful
            "notes": {"purpose": "AgentFront Tier 0 Razorpay connectivity smoke test"},
        }
    )


def write_checkout_helper(order: dict, key_id: str) -> Path:
    """Write a local Checkout page for the given order. UPI is preselected and
    prefilled with the test-mode auto-success VPA (one click: Verify, Pay).
    Card stays available as a second tab -- currently blocked on this account
    by an unrelated restriction, but the code path stays wired for when it's
    lifted."""
    out_path = Path(tempfile.gettempdir()) / f"razorpay_smoke_checkout_{order['id']}.html"
    html = f"""<!doctype html>
<html>
<head><meta charset="utf-8"><title>AgentFront Razorpay smoke test checkout</title></head>
<body>
<h3>AgentFront -- Razorpay test-mode checkout</h3>
<p>Order: {order["id"]} -- amount {order["amount"]} {order["currency"]}</p>
<p><b>UPI (primary):</b> preselected below, VPA prefilled with <code>{TEST_UPI_VPA}</code>
   -- click Verify, then Pay. Instant simulated success, no real UPI app needed.</p>
<p><b>Card (fallback):</b> switch tabs in the Checkout modal, use 4111 1111 1111 1111,
   any future expiry, any CVV. Currently blocked on this account by an "International Card
   Not Allowed" restriction -- unrelated to this code; ticket open with Razorpay.</p>
<button id="pay">Pay (test mode)</button>
<p id="result"></p>
<script src="{CHECKOUT_JS_URL}"></script>
<script>
document.getElementById('pay').onclick = function () {{
  var rzp = new Razorpay({{
    key: "{key_id}",
    amount: {order["amount"]},
    currency: "{order["currency"]}",
    order_id: "{order["id"]}",
    name: "AgentFront smoke test",
    description: "Tier 0 connectivity check",
    prefill: {{
      method: "upi",
      vpa: "{TEST_UPI_VPA}"
    }},
    handler: function (response) {{
      document.getElementById('result').innerHTML =
        "<b>Payment ID:</b> " + response.razorpay_payment_id +
        "<br>Run: <code>python scripts/razorpay_smoke.py --payment-id " +
        response.razorpay_payment_id + "</code>";
    }},
  }});
  rzp.open();
}};
</script>
</body>
</html>"""
    out_path.write_text(html, encoding="utf-8")
    return out_path


def serve_and_open(checkout_path: Path) -> str:
    """Serve checkout_path over http://127.0.0.1 (loopback only, ephemeral
    port) and open it in the default browser.

    file:// URLs are known to be unreliable for embedded checkout widgets --
    some browsers restrict things Razorpay's iframe/postMessage handshake
    relies on for pages loaded that way. A real (if local-only) HTTP origin
    avoids that whole class of problem. The server runs in a daemon thread
    and is shut down a few seconds after opening -- long enough for the page
    to finish loading; the Razorpay modal itself talks to Razorpay's own
    servers after that; it doesn't depend on ours staying up.
    """
    directory = str(checkout_path.parent)
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=directory)
    httpd = socketserver.TCPServer(("127.0.0.1", 0), handler)
    port = httpd.server_address[1]

    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()

    url = f"http://127.0.0.1:{port}/{checkout_path.name}"
    opened = webbrowser.open(url)
    time.sleep(3)
    httpd.shutdown()

    if not opened:
        print("      Could not auto-open a browser -- open the URL below manually.")
    return url


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--payment-id",
        help="A real payment_id from a completed test checkout, to exercise the capture call.",
    )
    args = parser.parse_args()

    client, key_id = get_client()

    print("=" * 72)
    print(f"Using key: {key_id[:14]}... (test mode confirmed)")

    print("\n[1/3] Creating test-mode Order...")
    order = create_test_order(client)
    print(f"      OK  id={order['id']}  status={order['status']}  amount={order['amount']} {order['currency']} (manual capture)")

    print("\n[2/3] Fetching the order back...")
    fetched = client.order.fetch(order["id"])
    assert fetched["id"] == order["id"], "fetched order id does not match created order"
    print(f"      OK  fetch matches created order (status={fetched['status']})")

    print("\n[3/3] Capture path...")
    if args.payment_id:
        try:
            result = client.payment.capture(args.payment_id, order["amount"], {"currency": order["currency"]})
            print(f"      OK  payment {args.payment_id} captured -- status={result['status']}, amount={result['amount']}")
        except Exception as e:  # noqa: BLE001 -- top-level smoke test: report and exit, don't crash on traceback
            print(f"      FAILED capture call: {e}")
            sys.exit(1)
    else:
        checkout_path = write_checkout_helper(order, key_id)
        print("      Order create + fetch verified above. Capture itself is NOT exercised yet --")
        print("      Razorpay has no server-side way to create a completed payment on this account")
        print("      (S2S UPI Collect and the generic S2S JSON endpoint both 404 -- not provisioned).")
        print("\n      Opening the checkout page in your browser (served locally, not file://)...")
        url = serve_and_open(checkout_path)
        print(f"        {url}")
        print("      That page has just loaded a 'Pay (test mode)' button -- click it. THAT opens")
        print("      Razorpay's actual checkout modal (a separate popup/overlay) with the UPI tab")
        print(f"      and VPA field. UPI (primary, one click): preselected, prefilled with {TEST_UPI_VPA}")
        print("      -- click Verify, then Pay. Card (fallback): 4111 1111 1111 1111, any future")
        print("      expiry/CVV -- currently blocked by an account-level 'International Card Not")
        print("      Allowed' restriction (ticket open).")
        print("      Then re-run: python scripts/razorpay_smoke.py --payment-id <the id shown>")

    print("\n" + "=" * 72)


if __name__ == "__main__":
    main()
