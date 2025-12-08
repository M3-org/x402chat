#!/usr/bin/env python3
"""
Fix existing test receivers that have NULL pay_to_address.

This script patches existing receivers to use their public_key as pay_to_address,
matching the new default behavior for new signups.
"""

from app import SessionLocal, ReceiverId

def main():
    db = SessionLocal()
    try:
        # Find all receivers without pay_to_address configured
        receivers = db.query(ReceiverId).filter(
            (ReceiverId.pay_to_address == None) | (ReceiverId.pay_to_address == "")
        ).all()

        if not receivers:
            print("✅ No receivers need fixing - all have pay_to_address configured")
            return

        print(f"Found {len(receivers)} receiver(s) without pay_to_address:\n")

        for receiver in receivers:
            print(f"  Username: {receiver.username or '(none)'}")
            print(f"  ID: {receiver.id}")
            print(f"  Public Key: {receiver.public_key}")
            print(f"  Old pay_to_address: {receiver.pay_to_address or '(NULL)'}")

            # Set pay_to_address to their sign-in wallet
            receiver.pay_to_address = receiver.public_key

            print(f"  New pay_to_address: {receiver.pay_to_address}")
            print()

        # Commit all changes
        db.commit()
        print(f"✅ Successfully updated {len(receivers)} receiver(s)")
        print("\nReceivers can now receive donations to their sign-in wallet.")
        print("They can still change this in dashboard settings if needed.")

    except Exception as e:
        db.rollback()
        print(f"❌ Error: {e}")
        raise
    finally:
        db.close()

if __name__ == "__main__":
    main()
