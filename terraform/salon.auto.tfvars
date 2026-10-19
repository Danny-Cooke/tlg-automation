# Hand-written salon facts the bot may quote. Not secret, so this file is committed.
#
# Staff, services and who-does-what are NOT here: they are generated from
# Fresha into fresha-menu.auto.tfvars.json by the menu sync Lambda (or
# `python -m menu_sync` from a laptop). Edit those in Fresha, not in git.
# Google accounts for the calendar checklist go in `calendar_emails` below.
# Secrets and per-environment values go in terraform.tfvars (git-ignored).

salon = {
  name                 = "The Looking Glass Beauty"
  address              = "4a Roushill, Shrewsbury, SY1 1PQ"
  phone                = "01743 669166"
  general_booking_link = "https://www.fresha.com/book-now/tlg-beauty-limited-xexbl23r/all-offer?share=true&pId=1453889"
  venue_url            = "https://www.fresha.com/en-GB/a/the-looking-glass-beauty-shrewsbury-roushill-xa3bpl74"
  # Fresha hours (what clients can actually book). The website shows 9:30 starts; confirm which is right.
  opening_hours = {
    monday    = "Closed"
    tuesday   = "10:00am to 6:00pm"
    wednesday = "10:00am to 6:00pm"
    thursday  = "10:00am to 10:00pm"
    friday    = "10:00am to 6:00pm"
    saturday  = "10:00am to 6:00pm"
    sunday    = "Closed"
  }
  extra_notes = <<-EOT
    Website: https://tlg-beauty.co.uk/. Email: info@tlg-beauty.co.uk. WhatsApp: 07512 574127.
    Parking available nearby, near public transport, wheelchair accessible, kid-friendly.
    The salon is several specialists under one roof. Each person has their own booking link;
    the general link shows everything.
    Nail services come in two tiers: "Senior Nail Services - TLG" (Jess, Sav, Carmen) and
    "Nails by TLG" (junior techs: Amber, and apprentice Lissy; cheaper, qualified and supervised,
    may take a little longer).
    Hair colour services need a patch test at least 24 hours before the appointment.
    Clients can also book a group appointment on the same Fresha link.
    Prices marked "from" depend on consultation, length or thickness.
    Tiny Tattoo Tuesdays: fine-line tattoos up to 3x3 inches for a reduced price, Tuesdays only.
    The salon has an Alice in Wonderland / steampunk theme ("Where Beauty Meets Alchemy").
    Children's pamper parties are called "Mini Hatters Pamper" at The Little Looking Glass.
  EOT
}

# Google account each person links Fresha to, keyed by the staff slug from
# fresha-menu.auto.tfvars.json. Leave empty while the repo is public.
calendar_emails = {}

# The Facebook Page the bots answer for. Public, not a secret.
meta_page_id = "61577501519464"
