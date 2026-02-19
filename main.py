from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    ReplyKeyboardMarkup,
    KeyboardButton
)
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ConversationHandler,
    ContextTypes,
    filters,
)
from telegram.error import TimedOut

# ==============================
# CONFIG
# ==============================
import os
TOKEN = os.environ.get("TELEGRAM_TOKEN")
CHANNEL_ID = "@titanshuttle"
ALLOWED_DRIVERS = [1262116449]
MAX_SEATS = 5

PLATE, PHOTO, COLOR, START, LOCATION, END, PRICE = range(7)

rides = {}
active_rides = {}

driver_keyboard = ReplyKeyboardMarkup(
    [["New Ride", "Update Plate", "Update Photo", "My ID"]],
    resize_keyboard=True
)


# ==============================
# UTIL
# ==============================
def generate_seat_buttons(seats_left):
    buttons = []
    row = []
    for i in range(1, seats_left + 1):
        row.append(InlineKeyboardButton(f"{i} Seat", callback_data=str(i)))
        if len(row) == 3:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)
    return buttons


# ==============================
# HANDLERS
# ==============================
async def myid(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(f"Your Telegram ID is:\n{update.effective_user.id}")


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id in ALLOWED_DRIVERS:
        await update.message.reply_text("🚖 TITAN Shuttle Driver Panel", reply_markup=driver_keyboard)
    else:
        await update.message.reply_text("🚖 TITAN Shuttle")


async def newride(update: Update, context: ContextTypes.DEFAULT_TYPE):
    driver_id = update.effective_user.id
    if driver_id not in ALLOWED_DRIVERS:
        await update.message.reply_text("❌ Not authorized.")
        return ConversationHandler.END
    if driver_id in active_rides:
        await update.message.reply_text("❌ You already have an active ride.")
        return ConversationHandler.END

    if "plate" not in context.user_data:
        await update.message.reply_text("Enter plate number:")
        return PLATE
    if "vehicle_photo" not in context.user_data:
        await update.message.reply_text("Send vehicle photo:")
        return PHOTO

    await update.message.reply_text("Enter car color:")
    return COLOR


async def update_plate_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Enter new plate number:")
    return PLATE


async def update_photo_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Send new vehicle photo:")
    return PHOTO


async def plate(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["plate"] = update.message.text
    await update.message.reply_text("✅ Plate saved.")
    if "vehicle_photo" not in context.user_data:
        await update.message.reply_text("Send vehicle photo:")
        return PHOTO
    return ConversationHandler.END


async def vehicle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["vehicle_photo"] = update.message.photo[-1].file_id
    await update.message.reply_text("✅ Photo saved.")
    if "color" not in context.user_data:
        await update.message.reply_text("Enter car color:")
        return COLOR
    return ConversationHandler.END


async def color(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["color"] = update.message.text
    await update.message.reply_text("Enter start location name:")
    return START


async def start_location(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["start"] = update.message.text
    location_button = KeyboardButton("📍 Share Location", request_location=True)
    keyboard = ReplyKeyboardMarkup([[location_button]], resize_keyboard=True, one_time_keyboard=True)
    await update.message.reply_text("Share your current GPS location:", reply_markup=keyboard)
    return LOCATION


async def location_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["latitude"] = update.message.location.latitude
    context.user_data["longitude"] = update.message.location.longitude
    await update.message.reply_text("Location received ✅\nEnter destination:", reply_markup=driver_keyboard)
    return END


async def end_location(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["end"] = update.message.text
    await update.message.reply_text("Enter price (ETB):")
    return PRICE


async def price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    driver_id = update.effective_user.id
    context.user_data["price"] = update.message.text

    p, c, s, e = context.user_data["plate"], context.user_data["color"], context.user_data["start"], context.user_data[
        "end"]
    pr, ph = context.user_data["price"], context.user_data["vehicle_photo"]
    lat, lon = context.user_data.get("latitude"), context.user_data.get("longitude")

    maps_link = f"https://www.google.com/maps?q={lat},{lon}" if lat else "N/A"
    caption = f"🚖 TITAN Shuttle\n\nFrom: {s}\nTo: {e}\nPrice: {pr} ETB\nPlate: {p}\nColor: {c}\n\nSeats Available: {MAX_SEATS}\nReserved: 0\n📍 {maps_link}"

    # 1. Post to Channel
    channel_msg = await context.bot.send_photo(
        chat_id=CHANNEL_ID,
        photo=ph,
        caption=caption,
        reply_markup=InlineKeyboardMarkup(generate_seat_buttons(MAX_SEATS))
    )

    # 2. Store data
    rides[channel_msg.message_id] = {"seats": MAX_SEATS, "reserved_count": 0, "driver": driver_id,
                                     "route": f"{s} → {e}"}
    active_rides[driver_id] = channel_msg.message_id

    # 3. Send START RIDE button to Driver (this deletes the channel post)
    start_btn = InlineKeyboardMarkup(
        [[InlineKeyboardButton("🚀 Start Ride (Close Post)", callback_data=f"start_trip_{channel_msg.message_id}")]])
    await update.message.reply_text(f"✅ Ride posted to {CHANNEL_ID}!", reply_markup=driver_keyboard)
    await update.message.reply_text(
        "Click below when you are ready to move. This will remove the post from the channel:", reply_markup=start_btn)

    return ConversationHandler.END


# ==============================
# BUTTON HANDLER (Logic for Delete)
# ==============================
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    driver_id = query.from_user.id

    try:
        await query.answer()
    except TimedOut:
        return

    # LOGIC: If driver clicks "Start Ride"
    if query.data.startswith("start_trip_"):
        channel_msg_id = int(query.data.split("_")[-1])
        try:
            await context.bot.delete_message(chat_id=CHANNEL_ID, message_id=channel_msg_id)
            await query.message.edit_text("✅ Trip Started! The post has been removed from the channel.")
        except Exception as e:
            await query.message.edit_text("⚠️ Could not delete post (maybe already deleted).")

        if driver_id in active_rides: del active_rides[driver_id]
        if channel_msg_id in rides: del rides[channel_msg_id]
        return

    # LOGIC: If user clicks a "Seat" button
    msg_id = query.message.message_id
    if msg_id not in rides:
        await query.answer("Ride no longer available.", show_alert=True)
        return

    ride = rides[msg_id]
    seats_requested = int(query.data)
    if ride["seats"] < seats_requested:
        await query.answer("Not enough seats!", show_alert=True)
        return

    ride["seats"] -= seats_requested
    ride["reserved_count"] += seats_requested

    # Notify driver
    user = query.from_user
    name = f"@{user.username}" if user.username else user.first_name
    await context.bot.send_message(ride["driver"],
                                   f"🔔 Reservation: {name} booked {seats_requested} seat(s) for {ride['route']}")

    # Update channel post
    new_cap = query.message.caption.split("Seats Available")[
                  0] + f"Seats Available: {ride['seats']}\nReserved: {ride['reserved_count']}"
    kb = InlineKeyboardMarkup(generate_seat_buttons(ride["seats"])) if ride["seats"] > 0 else None
    await query.message.edit_caption(caption=new_cap, reply_markup=kb)


# ==============================
# MAIN
# ==============================
app = ApplicationBuilder().token(TOKEN).connect_timeout(30).read_timeout(30).build()

conv_handler = ConversationHandler(
    entry_points=[
        MessageHandler(filters.Text("New Ride"), newride),
        MessageHandler(filters.Text("Update Plate"), update_plate_command),
        MessageHandler(filters.Text("Update Photo"), update_photo_command),
    ],
    states={
        PLATE: [MessageHandler(filters.TEXT & ~filters.COMMAND, plate)],
        PHOTO: [MessageHandler(filters.PHOTO, vehicle_photo)],
        COLOR: [MessageHandler(filters.TEXT & ~filters.COMMAND, color)],
        START: [MessageHandler(filters.TEXT & ~filters.COMMAND, start_location)],
        LOCATION: [MessageHandler(filters.LOCATION, location_received)],
        END: [MessageHandler(filters.TEXT & ~filters.COMMAND, end_location)],
        PRICE: [MessageHandler(filters.TEXT & ~filters.COMMAND, price)],
    },
    fallbacks=[CommandHandler("start", start)],
)

app.add_handler(CommandHandler("start", start))
app.add_handler(MessageHandler(filters.Text("My ID"), myid))
app.add_handler(conv_handler)
app.add_handler(CallbackQueryHandler(button_handler))

print("🚀 TITAN Shuttle Bot Running...")

app.run_polling()

