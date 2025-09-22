import logging
import asyncio
import random
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, asdict
from enum import Enum

from aiogram import Bot, Dispatcher, Router, F
from aiogram.types import (
    Message, WebAppInfo, InlineKeyboardMarkup, InlineKeyboardButton, 
    CallbackQuery, ChatPermissions, FSInputFile
)
from aiogram.filters import Command, CommandObject, Filter
from aiogram.enums import ParseMode, ChatMemberStatus
from aiogram.client.default import DefaultBotProperties
from aiogram.methods import SetChatMenuButton, PinChatMessage, UnpinChatMessage
from aiogram.types import MenuButtonWebApp, User
from aiogram.exceptions import TelegramBadRequest
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

import os
BOT_TOKEN = os.getenv("BOT_TOKEN")
WEBSITE_URL = "https://mosachi01.github.io/my-science-hub/"
LOGO_URL = "https://i.imgur.com/5X4XZqE.png"

# ===== تكوين التسجيل المتقدم =====
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("bot.log", encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# ===== تهيئة البوت والموزع =====
bot = Bot(
    token=BOT_TOKEN,
    default=DefaultBotProperties(parse_mode=ParseMode.HTML)
)

dp = Dispatcher()
router = Router()
dp.include_router(router)

# ===== تعريف الحالات والهياكل =====
class SessionStates(StatesGroup):
    ACTIVE = State()
    PAUSED = State()
    COMPLETED = State()

class UserStatus(Enum):
    ACTIVE = "active"
    INACTIVE = "inactive"
    BANNED = "banned"

@dataclass
class StudySession:
    session_id: str
    chat_id: int
    creator_id: int
    creator_name: str
    participants: Dict[int, Dict[str, Any]]
    message_id: Optional[int] = None
    start_time: float = 0
    time_left: int = 55 * 60  # 55 دقيقة
    is_active: bool = True
    is_pinned: bool = False
    last_update: datetime = None
    stats: Dict[str, Any] = None
    timer_task: Optional[asyncio.Task] = None

@dataclass
class UserProfile:
    user_id: int
    username: Optional[str]
    first_name: str
    last_name: Optional[str]
    join_date: datetime
    status: UserStatus = UserStatus.ACTIVE
    study_stats: Dict[str, Any] = None
    achievements: List[str] = None
    preferences: Dict[str, Any] = None

# ===== قواعد البيانات الافتراضية =====
group_sessions: Dict[str, StudySession] = {}
user_profiles: Dict[int, UserProfile] = {}
active_sessions: Dict[int, str] = {}  # chat_id -> session_id
pinned_messages: Dict[int, int] = {}  # chat_id -> message_id
bot_stats: Dict[str, Any] = {
    "total_sessions": 0,
    "active_users": 0,
    "total_participations": 0,
    "start_time": datetime.now()
}

# ===== أدوات المساعدة =====
def get_display_name(user: User) -> str:
    """الحصول على اسم العرض للمستخدم"""
    if user.username:
        return f"@{user.username}"
    elif user.last_name:
        return f"{user.first_name} {user.last_name}"
    else:
        return user.first_name

def format_time(seconds: int) -> str:
    """تنسيق الوقت بالدقائق والثواني"""
    minutes = seconds // 60
    secs = seconds % 60
    if minutes >= 60:
        hours = minutes // 60
        mins = minutes % 60
        return f"{hours:02d}:{mins:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"

def generate_session_id(chat_id: int) -> str:
    """توليد معرف جلسة فريد"""
    timestamp = int(datetime.now().timestamp())
    return f"session_{chat_id}_{timestamp}_{random.randint(1000, 9999)}"

def get_random_motivation() -> str:
    """الحصول على رسالة تحفيزية عشوائية"""
    motivations = [
        "🔥 استمر، فالنجاح قريب!",
        "💪 لا تتوقف، أنت على الطريق الصحيح!",
        "🌟 كل دقيقة دراسة تقربك من حلمك!",
        "🎯 ركّز، فالفوز بيديك!",
        "🚀 استمر في التقدم، أنت بطل!",
        "✨ الجهد اليوم يصنع الفارق غداً!",
        "🏆 أنت أقوى مما تتخيل!",
        "💫 ثق أنك ستصل إلى القمة!"
    ]
    return random.choice(motivations)

def get_random_emoji() -> str:
    """الحصول على إيموجي عشوائي"""
    emojis = ["📚", "📖", "🎓", "💡", "🧠", "🎯", "🔥", "⭐", "🌟", "✨", "🚀", "🏆", "💪", "🎯"]
    return random.choice(emojis)

# ===== إدارة المستخدمين =====
async def create_user_profile(user: User) -> UserProfile:
    """إنشاء ملف تعريف للمستخدم"""
    profile = UserProfile(
        user_id=user.id,
        username=user.username,
        first_name=user.first_name,
        last_name=user.last_name,
        join_date=datetime.now(),
        study_stats={
            "total_sessions": 0,
            "total_time": 0,
            "completed_sessions": 0,
            "last_session": None
        },
        achievements=[],
        preferences={
            "notifications": True,
            "motivation_messages": True,
            "language": "ar"
        }
    )
    user_profiles[user.id] = profile
    bot_stats["active_users"] += 1
    return profile

async def get_user_profile(user_id: int) -> UserProfile:
    """الحصول على ملف تعريف المستخدم"""
    if user_id not in user_profiles:
        # إنشاء ملف تعريف افتراضي إذا لم يكن موجوداً
        try:
            user = await bot.get_chat(user_id)
            return await create_user_profile(user)
        except Exception as e:
            logger.error(f"خطأ في إنشاء ملف تعريف للمستخدم {user_id}: {e}")
            # إنشاء ملف تعريف أساسي
            return UserProfile(
                user_id=user_id,
                username=None,
                first_name="مستخدم",
                last_name=None,
                join_date=datetime.now(),
                study_stats={"total_sessions": 0, "total_time": 0, "completed_sessions": 0, "last_session": None},
                achievements=[],
                preferences={"notifications": True, "motivation_messages": True, "language": "ar"}
            )
    return user_profiles[user_id]

async def update_user_stats(user_id: int, session_duration: int = 0):
    """تحديث إحصائيات المستخدم"""
    try:
        profile = await get_user_profile(user_id)
        profile.study_stats["total_sessions"] += 1
        profile.study_stats["total_time"] += session_duration
        profile.study_stats["last_session"] = datetime.now()
        
        if session_duration >= 50 * 60:  # إذا اكتملت الجلسة
            profile.study_stats["completed_sessions"] += 1
            # إضافة إنجاز إذا كان هذا أول إكمال
            if "first_completion" not in profile.achievements:
                profile.achievements.append("first_completion")
    except Exception as e:
        logger.error(f"خطأ في تحديث إحصائيات المستخدم {user_id}: {e}")

# ===== إدارة الجلسات =====
async def create_study_session(chat_id: int, creator: User) -> StudySession:
    """إنشاء جلسة دراسية جديدة"""
    session_id = generate_session_id(chat_id)
    
    session = StudySession(
        session_id=session_id,
        chat_id=chat_id,
        creator_id=creator.id,
        creator_name=get_display_name(creator),
        participants={},
        start_time=asyncio.get_event_loop().time(),
        time_left=55 * 60,
        is_active=True,
        last_update=datetime.now(),
        stats={
            "joins": 0,
            "leaves": 0,
            "extensions": 0,
            "completions": 0
        }
    )
    
    group_sessions[session_id] = session
    active_sessions[chat_id] = session_id
    bot_stats["total_sessions"] += 1
    
    return session

async def get_active_session(chat_id: int) -> Optional[StudySession]:
    """الحصول على الجلسة النشطة في المجموعة"""
    if chat_id in active_sessions:
        session_id = active_sessions[chat_id]
        if session_id in group_sessions:
            return group_sessions[session_id]
    return None

async def end_session(session_id: str) -> Optional[StudySession]:
    """إنهاء الجلسة"""
    if session_id in group_sessions:
        session = group_sessions[session_id]
        session.is_active = False
        
        # إلغاء مؤقت الجلسة إذا كان موجوداً
        if session.timer_task and not session.timer_task.done():
            session.timer_task.cancel()
        
        # إزالة من القوائم النشطة
        if session.chat_id in active_sessions:
            del active_sessions[session.chat_id]
        
        # تحديث إحصائيات المستخدمين
        for user_id in session.participants:
            try:
                await update_user_stats(user_id, 55 * 60 - session.time_left)
            except Exception as e:
                logger.error(f"خطأ في تحديث إحصائيات المستخدم {user_id}: {e}")
        
        return session
    return None

# ===== فلاتر مخصصة =====
class IsGroupChat(Filter):
    async def __call__(self, message: Message) -> bool:
        return message.chat.type in ["group", "supergroup"]

class IsPrivateChat(Filter):
    async def __call__(self, message: Message) -> bool:
        return message.chat.type == "private"

class IsAdmin(Filter):
    async def __call__(self, obj) -> bool:
        try:
            if isinstance(obj, Message):
                member = await bot.get_chat_member(obj.chat.id, obj.from_user.id)
                return member.status in [ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.CREATOR]
            elif isinstance(obj, CallbackQuery):
                member = await bot.get_chat_member(obj.message.chat.id, obj.from_user.id)
                return member.status in [ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.CREATOR]
        except Exception as e:
            logger.error(f"خطأ في التحقق من الصلاحيات: {e}")
            return False

# ===== معالجة الأخطاء =====
async def handle_error(error: Exception, context: str = ""):
    """معالجة الأخطاء العامة"""
    logger.error(f"خطأ في {context}: {str(error)}")
    # يمكن إضافة إرسال تنبيه للمطور هنا

# ===== الأوامر الأساسية =====

@router.message(Command("start"))
async def start_handler(message: Message, command: CommandObject):
    """معالجة أمر /start"""
    try:
        user = message.from_user
        user_name = get_display_name(user)
        
        # تحديث ملف تعريف المستخدم
        await get_user_profile(user.id)
        
        welcome_messages = [
            f"🌟 مرحباً بك يا <b>{user_name}</b> في بوت الدراسة الذكي!",
            f"📚 أهلاً وسهلاً يا <b>{user_name}</b> في منصتنا التعليمية!",
            f"🚀 مرحباً يا <b>{user_name}</b>! مستعد للبدء في رحلة التعلم؟",
            f"🎯 أهلاً بك يا <b>{user_name}</b>! لنحقق أهدافك معاً!",
            f"🔥 مرحباً يا <b>{user_name}</b>! استعد لتجربة دراسية مميزة!"
        ]
        
        welcome_message = random.choice(welcome_messages)
        
        # إعداد زر القائمة
        try:
            await bot(SetChatMenuButton(
                chat_id=message.chat.id,
                menu_button=MenuButtonWebApp(
                    text="🌐 الموقع",
                    web_app=WebAppInfo(url=WEBSITE_URL)
                )
            ))
        except Exception as e:
            logger.error(f"خطأ في تعيين زر القائمة: {e}")
        
        # لوحة المفاتيح الرئيسية
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="📚 بدء جلسة دراسية", callback_data="start_session_info")],
            [InlineKeyboardButton(text="📊 إحصائياتي", callback_data="my_stats")],
            [InlineKeyboardButton(text="❓ المساعدة", callback_data="help")]
        ])
        
        await message.answer(
            f"{welcome_message}\n\n"
            f"✨ هذا البوت مصمم لمساعدتك في تنظيم جلسات الدراسة الجماعية.\n"
            f"🎯 ميزات البوت:\n"
            f"• ⏰ مؤقت دراسي تفاعلي\n"
            f"• 👥 إدارة المشاركين\n"
            f"• 📊 تتبع التقدم\n"
            f"• 🎯 تحفيز مستمر\n"
            f"• 🔗 ربط مباشر بالموقع التعليمي\n\n"
            f"{get_random_motivation()}",
            reply_markup=keyboard
        )
    except Exception as e:
        await handle_error(e, "start_handler")

@router.message(Command("pinlink"), IsGroupChat())
async def pin_website_message(message: Message):
    """تثبيت رسالة مع رابط الموقع"""
    try:
        # التحقق من الصلاحيات
        try:
            member = await bot.get_chat_member(message.chat.id, message.from_user.id)
            if member.status not in [ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.CREATOR]:
                await message.answer("❌ يجب أن تكون مسؤولاً في هذه المجموعة لتثبيت الرسائل.")
                return
        except Exception as e:
            await message.answer(f"❌ حدث خطأ في التحقق من الصلاحيات: {e}")
            return
        
        # إنشاء لوحة المفاتيح
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🌐 فتح موقع الجامعة", web_app=WebAppInfo(url=WEBSITE_URL))],
            [InlineKeyboardButton(text="📚 المواد الدراسية", web_app=WebAppInfo(url=f"{WEBSITE_URL}#subjects"))],
            [InlineKeyboardButton(text="📖 المكتبة", web_app=WebAppInfo(url=f"{WEBSITE_URL}#library"))]
        ])
        
        # إرسال وتثبيت الرسالة
        try:
            sent_message = await message.answer(
                f"🎓 <b>منصة جامعة العلوم</b>\n\n"
                f"📚 الوصول السريع إلى المحتوى التعليمي:\n"
                f"• 📖 المواد الدراسية\n"
                f"• 📚 المكتبة الرقمية\n"
                f"• 🎯 أدوات الدراسة\n"
                f"• 💡 موارد تعليمية متنوعة\n\n"
                f"🚀 اضغط على الأزرار أدناه للوصول المباشر:",
                reply_markup=keyboard
            )
            
            # تثبيت الرسالة
            await bot(PinChatMessage(
                chat_id=message.chat.id,
                message_id=sent_message.message_id,
                disable_notification=False
            ))
            
            # تخزين معرف الرسالة المثبتة
            pinned_messages[message.chat.id] = sent_message.message_id
            
            await message.answer("✅ تم تثبيت رسالة الوصول السريع إلى الموقع في المجموعة.")
            
        except Exception as e:
            await message.answer(f"❌ لم أتمكن من تثبيت الرسالة: {e}")
    except Exception as e:
        await handle_error(e, "pin_website_message")

@router.message(Command("startsession"), IsGroupChat())
async def start_session_group(message: Message):
    """بدء جلسة دراسية جديدة"""
    try:
        # التحقق من الصلاحيات
        try:
            member = await bot.get_chat_member(message.chat.id, message.from_user.id)
            if member.status not in [ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.CREATOR]:
                await message.answer("❌ يجب أن تكون مسؤولاً في هذه المجموعة لبدء الجلسة.")
                return
        except Exception as e:
            await message.answer(f"❌ حدث خطأ في التحقق من الصلاحيات: {e}")
            return
        
        # التحقق من وجود جلسة نشطة
        active_session = await get_active_session(message.chat.id)
        if active_session:
            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="❌ إنهاء الجلسة الحالية", callback_data=f"end_session_{active_session.session_id}")],
                [InlineKeyboardButton(text="📊 عرض حالة الجلسة", callback_data=f"session_status_{active_session.session_id}")]
            ])
            await message.answer(
                "⚠️ هناك جلسة نشطة بالفعل في هذه المجموعة.\n"
                "هل ترغب في إنهاء الجلسة الحالية؟",
                reply_markup=keyboard
            )
            return
        
        # إنشاء جلسة جديدة
        session = await create_study_session(message.chat.id, message.from_user)
        
        # إنشاء لوحة المفاتيح
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✅ انضمام للجلسة", callback_data=f"join_{session.session_id}")],
            [InlineKeyboardButton(text="👥 المشاركون (0)", callback_data=f"participants_{session.session_id}")],
            [InlineKeyboardButton(text="⏹️ إنهاء الجلسة", callback_data=f"end_session_{session.session_id}")]
        ])
        
        # إرسال رسالة الجلسة
        try:
            sent_message = await message.answer_photo(
                photo=LOGO_URL,
                caption=(
                    f"🎓 <b>جلسة دراسية جديدة</b>\n"
                    f"🕒 <b>المدة:</b> 55 دقيقة\n"
                    f"👤 <b>المؤسس:</b> {session.creator_name}\n"
                    f"⏰ <b>الوقت المتبقي:</b> {format_time(session.time_left)}\n\n"
                    f"👥 <b>المشاركون:</b> لا أحد بعد\n"
                    f"📊 <b>الحالة:</b> <code>قيد الانتظار</code>\n\n"
                    f"{get_random_motivation()}"
                ),
                reply_markup=keyboard
            )
            
            session.message_id = sent_message.message_id
            
            # تثبيت الرسالة تلقائياً
            try:
                await bot(PinChatMessage(
                    chat_id=message.chat.id,
                    message_id=sent_message.message_id,
                    disable_notification=True
                ))
                session.is_pinned = True
            except Exception as e:
                logger.warning(f"لم أتمكن من تثبيت رسالة الجلسة: {e}")
            
        except Exception as e:
            await message.answer(f"❌ حدث خطأ في إنشاء الجلسة: {e}")
    except Exception as e:
        await handle_error(e, "start_session_group")

# ===== معالجات الأزرار =====

@router.callback_query(F.data == "start_session_info")
async def start_session_info(callback_query: CallbackQuery):
    """معلومات عن بدء الجلسة"""
    try:
        # التحقق من نوع المحادثة
        if callback_query.message.chat.type in ["group", "supergroup"]:
            # في المجموعة - إرسال تعليمات
            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="✅ فهمت", callback_data="back_to_main")]
            ])
            
            await callback_query.message.edit_text(
                "📢 <b>لبدء جلسة دراسية في المجموعة:</b>\n\n"
                "1. أضف البوت إلى المجموعة\n"
                "2. اجعله مسؤولاً في المجموعة\n"
                "3. استخدم الأمر <code>/startsession</code>\n\n"
                "💡 ملاحظة: يمكن فقط للمشرفين بدء الجلسات.",
                reply_markup=keyboard
            )
        else:
            # في الخاص - بدء الجلسة مباشرة
            user = callback_query.from_user
            chat_id = callback_query.message.chat.id
            
            # إنشاء جلسة خاصة
            session_id = generate_session_id(chat_id)
            session = StudySession(
                session_id=session_id,
                chat_id=chat_id,
                creator_id=user.id,
                creator_name=get_display_name(user),
                participants={user.id: {"name": get_display_name(user), "join_time": datetime.now(), "active": True}},
                start_time=asyncio.get_event_loop().time(),
                time_left=55 * 60,
                is_active=True,
                last_update=datetime.now(),
                stats={"joins": 1, "leaves": 0, "extensions": 0, "completions": 0}
            )
            
            group_sessions[session_id] = session
            active_sessions[chat_id] = session_id
            bot_stats["total_sessions"] += 1
            
            # إرسال رسالة بدء الجلسة
            await callback_query.message.edit_text(
                f"🚀 <b>بدأت جلستك الآن!</b>\n"
                f"🕒 المدة: 55 دقيقة\n"
                f"🎯 ابقَ مركزاً لتحقيق أفضل النتائج.\n\n"
                f"📱 يمكنك الوصول إلى المحتوى التعليمي عبر الزر أدناه:",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="🌐 فتح الموقع", web_app=WebAppInfo(url=WEBSITE_URL))]
                ])
            )
            
            # بدء المؤقت
            session.timer_task = asyncio.create_task(private_session_timer(session_id))
        
        await callback_query.answer()
    except Exception as e:
        await handle_error(e, "start_session_info")
        await callback_query.answer("حدث خطأ، يرجى المحاولة مرة أخرى.", show_alert=True)

@router.callback_query(F.data == "my_stats")
async def show_user_stats(callback_query: CallbackQuery):
    """عرض إحصائيات المستخدم"""
    try:
        profile = await get_user_profile(callback_query.from_user.id)
        
        total_time_str = format_time(profile.study_stats["total_time"])
        completion_rate = (profile.study_stats["completed_sessions"] / max(profile.study_stats["total_sessions"], 1)) * 100
        
        achievements_text = "\n".join([f"🏆 {ach}" for ach in profile.achievements]) if profile.achievements else "لا توجد إنجازات بعد"
        
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="📈 تفاصيل أكثر", callback_data="detailed_stats")],
            [InlineKeyboardButton(text="🔙 رجوع", callback_data="back_to_main")]
        ])
        
        await callback_query.message.edit_text(
            f"📊 <b>إحصائياتك الدراسية</b>\n\n"
            f"👤 <b>الاسم:</b> {get_display_name(callback_query.from_user)}\n"
            f"📅 <b>تاريخ الانضمام:</b> {profile.join_date.strftime('%Y-%m-%d')}\n\n"
            f"📚 <b>الجلسات الإجمالية:</b> {profile.study_stats['total_sessions']}\n"
            f"✅ <b>الجلسات المكتملة:</b> {profile.study_stats['completed_sessions']}\n"
            f"⏱️ <b>إجمالي وقت الدراسة:</b> {total_time_str}\n"
            f"📊 <b>معدل الإنجاز:</b> {completion_rate:.1f}%\n\n"
            f"🏅 <b>الإنجازات:</b>\n{achievements_text}\n\n"
            f"{get_random_motivation()}",
            reply_markup=keyboard
        )
        await callback_query.answer()
    except Exception as e:
        await handle_error(e, "show_user_stats")
        await callback_query.answer("حدث خطأ، يرجى المحاولة مرة أخرى.", show_alert=True)

@router.callback_query(F.data.startswith("join_"))
async def join_session(callback_query: CallbackQuery):
    """الانضمام إلى الجلسة"""
    try:
        session_id = callback_query.data.split("_", 1)[1]
        user = callback_query.from_user
        
        # التحقق من وجود الجلسة
        if session_id not in group_sessions:
            await callback_query.answer("❌ الجلسة غير موجودة أو انتهت.", show_alert=True)
            return
        
        session = group_sessions[session_id]
        
        # التحقق من نشاط الجلسة
        if not session.is_active:
            await callback_query.answer("❌ الجلسة قد انتهت بالفعل.", show_alert=True)
            return
        
        # التحقق من تكرار الانضمام
        if user.id in session.participants:
            await callback_query.answer("✅ أنت منضم بالفعل!", show_alert=True)
            return
        
        # إضافة المستخدم إلى المشاركين
        session.participants[user.id] = {
            "name": get_display_name(user),
            "join_time": datetime.now(),
            "active": True
        }
        
        session.stats["joins"] += 1
        bot_stats["total_participations"] += 1
        
        # التحقق من عدد المشاركين لبدء الجلسة
        participant_count = len(session.participants)
        
        # إذا كان العدد 3 أو أكثر و لم يبدأ المؤقت
        if participant_count >= 3 and (not session.timer_task or session.timer_task.done()):
            # بدء مؤقت الجلسة
            session.timer_task = asyncio.create_task(group_session_timer(session_id))
        
        # تحديث رسالة الجلسة
        participant_list = "\n".join([f"• {p['name']}" for p in session.participants.values()])
        
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✅ انضمام للجلسة", callback_data=f"join_{session_id}")],
            [InlineKeyboardButton(text=f"👥 المشاركون ({participant_count})", callback_data=f"participants_{session_id}")],
            [InlineKeyboardButton(text="⏹️ إنهاء الجلسة", callback_data=f"end_session_{session_id}")]
        ])
        
        try:
            await bot.edit_message_caption(
                chat_id=session.chat_id,
                message_id=session.message_id,
                caption=(
                    f"🎓 <b>جلسة دراسية جارية</b>\n"
                    f"🕒 <b>المدة:</b> 55 دقيقة\n"
                    f"👤 <b>المؤسس:</b> {session.creator_name}\n"
                    f"⏰ <b>الوقت المتبقي:</b> {format_time(session.time_left)}\n\n"
                    f"👥 <b>المشاركون ({participant_count}):</b>\n{participant_list}\n\n"
                    f"📊 <b>الحالة:</b> <code>نشطة</code>\n\n"
                    f"{get_random_motivation()}"
                ),
                reply_markup=keyboard
            )
        except Exception as e:
            logger.error(f"خطأ في تحديث رسالة الجلسة: {e}")
        
        # إرسال رسالة ترحيب في الخاص
        try:
            welcome_keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🌐 فتح الموقع", web_app=WebAppInfo(url=WEBSITE_URL))],
                [InlineKeyboardButton(text="📊 إحصائياتي", callback_data="my_stats")],
                [InlineKeyboardButton(text="❓ المساعدة", callback_data="help")]
            ])
            
            await bot.send_message(
                chat_id=user.id,
                text=(
                    f"🚀 <b>مرحباً بك في جلسة الدراسة!</b>\n\n"
                    f"📚 الجلسة بدأت الآن لمدة 55 دقيقة.\n"
                    f"🎯 ابقَ مركزاً لتحقيق أفضل النتائج.\n\n"
                    f"📱 يمكنك الوصول إلى المحتوى التعليمي عبر الزر أدناه:"
                ),
                reply_markup=welcome_keyboard
            )
        except Exception as e:
            logger.warning(f"لم أتمكن من إرسال رسالة للمستخدم {user.id}: {e}")
        
        await callback_query.answer("✅ تم الانضمام إلى الجلسة بنجاح!", show_alert=True)
    except Exception as e:
        await handle_error(e, "join_session")
        await callback_query.answer("حدث خطأ، يرجى المحاولة مرة أخرى.", show_alert=True)

@router.callback_query(F.data.startswith("participants_"))
async def show_participants(callback_query: CallbackQuery):
    """عرض قائمة المشاركين"""
    try:
        session_id = callback_query.data.split("_", 1)[1]
        
        if session_id not in group_sessions:
            await callback_query.answer("❌ الجلسة غير موجودة.", show_alert=True)
            return
        
        session = group_sessions[session_id]
        participant_count = len(session.participants)
        
        if participant_count == 0:
            participants_text = "لا يوجد مشاركون بعد"
        else:
            participants_list = []
            for i, (user_id, participant) in enumerate(session.participants.items(), 1):
                status = "🟢" if participant["active"] else "🔴"
                participants_list.append(f"{i}. {status} {participant['name']}")
            participants_text = "\n".join(participants_list)
        
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔙 رجوع للجلسة", callback_data=f"back_to_session_{session_id}")],
            [InlineKeyboardButton(text="🔄 تحديث", callback_data=f"participants_{session_id}")]
        ])
        
        await callback_query.message.edit_text(
            f"👥 <b>المشاركون في الجلسة</b>\n"
            f"🔢 <b>العدد الإجمالي:</b> {participant_count}\n\n"
            f"{participants_text}\n\n"
            f"🟢 <b>نشط</b>  🔴 <b>غير نشط</b>",
            reply_markup=keyboard
        )
        await callback_query.answer()
    except Exception as e:
        await handle_error(e, "show_participants")
        await callback_query.answer("حدث خطأ، يرجى المحاولة مرة أخرى.", show_alert=True)

@router.callback_query(F.data.startswith("back_to_session_"))
async def back_to_session(callback_query: CallbackQuery):
    """العودة إلى عرض الجلسة"""
    try:
        session_id = callback_query.data.split("_", 3)[3]
        
        if session_id not in group_sessions:
            await callback_query.answer("❌ الجلسة غير موجودة.", show_alert=True)
            return
        
        session = group_sessions[session_id]
        participant_count = len(session.participants)
        participant_list = "\n".join([f"• {p['name']}" for p in session.participants.values()]) if session.participants else "لا أحد بعد"
        
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✅ انضمام للجلسة", callback_data=f"join_{session_id}")],
            [InlineKeyboardButton(text=f"👥 المشاركون ({participant_count})", callback_data=f"participants_{session_id}")],
            [InlineKeyboardButton(text="⏹️ إنهاء الجلسة", callback_data=f"end_session_{session_id}")]
        ])
        
        try:
            await bot.edit_message_caption(
                chat_id=session.chat_id,
                message_id=session.message_id,
                caption=(
                    f"🎓 <b>جلسة دراسية جارية</b>\n"
                    f"🕒 <b>المدة:</b> 55 دقيقة\n"
                    f"👤 <b>المؤسس:</b> {session.creator_name}\n"
                    f"⏰ <b>الوقت المتبقي:</b> {format_time(session.time_left)}\n\n"
                    f"👥 <b>المشاركون ({participant_count}):</b>\n{participant_list}\n\n"
                    f"📊 <b>الحالة:</b> <code>نشطة</code>\n\n"
                    f"{get_random_motivation()}"
                ),
                reply_markup=keyboard
            )
        except Exception as e:
            logger.error(f"خطأ في تحديث رسالة الجلسة: {e}")
        
        await callback_query.answer()
    except Exception as e:
        await handle_error(e, "back_to_session")
        await callback_query.answer("حدث خطأ، يرجى المحاولة مرة أخرى.", show_alert=True)

@router.callback_query(F.data == "back_to_main")
async def back_to_main_menu(callback_query: CallbackQuery):
    """العودة إلى القائمة الرئيسية"""
    try:
        user_name = get_display_name(callback_query.from_user)
        
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="📚 بدء جلسة دراسية", callback_data="start_session_info")],
            [InlineKeyboardButton(text="📊 إحصائياتي", callback_data="my_stats")],
            [InlineKeyboardButton(text="❓ المساعدة", callback_data="help")]
        ])
        
        await callback_query.message.edit_text(
            f"🌟 مرحباً بك يا <b>{user_name}</b> في بوت الدراسة الذكي!\n\n"
            f"✨ اختر من الخيارات التالية:",
            reply_markup=keyboard
        )
        await callback_query.answer()
    except Exception as e:
        await handle_error(e, "back_to_main_menu")
        await callback_query.answer("حدث خطأ، يرجى المحاولة مرة أخرى.", show_alert=True)

@router.callback_query(F.data == "help")
async def show_help(callback_query: CallbackQuery):
    """عرض المساعدة"""
    try:
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="📚 الأوامر الأساسية", callback_data="help_commands")],
            [InlineKeyboardButton(text="👥 إدارة الجلسات", callback_data="help_sessions")],
            [InlineKeyboardButton(text="🔙 رجوع", callback_data="back_to_main")]
        ])
        
        await callback_query.message.edit_text(
            "❓ <b>مركز المساعدة</b>\n\n"
            "هذا البوت مصمم لمساعدتك في تنظيم جلسات دراسية فعالة.\n\n"
            "اختر قسم المساعدة الذي ترغب في معرفة المزيد عنه:",
            reply_markup=keyboard
        )
        await callback_query.answer()
    except Exception as e:
        await handle_error(e, "show_help")
        await callback_query.answer("حدث خطأ، يرجى المحاولة مرة أخرى.", show_alert=True)

@router.callback_query(F.data == "help_commands")
async def help_commands(callback_query: CallbackQuery):
    """مساعدة الأوامر"""
    try:
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔙 رجوع", callback_data="help")]
        ])
        
        await callback_query.message.edit_text(
            "📚 <b>الأوامر الأساسية</b>\n\n"
            "<b>في المجموعات:</b>\n"
            "/startsession - بدء جلسة دراسية جديدة\n"
            "/pinlink - تثبيت رسالة الوصول السريع\n\n"
            "<b>في الخاص:</b>\n"
            "/start - بدء التفاعل مع البوت\n"
            "/stats - عرض إحصائياتك\n\n"
            "<b>ملاحظات:</b>\n"
            "• يجب أن يكون البوت مسؤولاً لبدء الجلسات\n"
            "• يمكن تثبيت رسائل فقط من قبل المشرفين",
            reply_markup=keyboard
        )
        await callback_query.answer()
    except Exception as e:
        await handle_error(e, "help_commands")
        await callback_query.answer("حدث خطأ، يرجى المحاولة مرة أخرى.", show_alert=True)

@router.callback_query(F.data.startswith("end_session_"))
async def end_session_callback(callback_query: CallbackQuery):
    """إنهاء الجلسة عبر الزر"""
    try:
        session_id = callback_query.data.split("_", 2)[2]
        
        # التحقق من الصلاحيات (فقط المشرفين يمكنهم إنهاء الجلسة)
        try:
            member = await bot.get_chat_member(callback_query.message.chat.id, callback_query.from_user.id)
            if member.status not in [ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.CREATOR]:
                await callback_query.answer("❌ يجب أن تكون مسؤولاً لإنهاء الجلسة.", show_alert=True)
                return
        except Exception as e:
            await callback_query.answer(f"❌ حدث خطأ في التحقق من الصلاحيات: {e}", show_alert=True)
            return
        
        # إنهاء الجلسة
        session = await end_session(session_id)
        
        if session:
            # تحديث رسالة الجلسة
            if session.message_id:
                try:
                    participant_count = len(session.participants)
                    participant_list = "\n".join([f"• {p['name']}" for p in session.participants.values()]) if session.participants else "لا أحد"
                    
                    await bot.edit_message_caption(
                        chat_id=session.chat_id,
                        message_id=session.message_id,
                        caption=(
                            f"⏹️ <b>تم إنهاء الجلسة!</b>\n"
                            f"🕒 <b>المدة:</b> 55 دقيقة\n"
                            f"👤 <b>المؤسس:</b> {session.creator_name}\n\n"
                            f"👥 <b>المشاركون ({participant_count}):</b>\n{participant_list}\n\n"
                            f"📌 <b>انتهت حصتكم، أحسنتم 👏</b>"
                        ),
                        reply_markup=None
                    )
                    
                    # إزالة التثبيت
                    if session.is_pinned:
                        try:
                            await bot(UnpinChatMessage(
                                chat_id=session.chat_id,
                                message_id=session.message_id
                            ))
                        except Exception as e:
                            logger.warning(f"لم أتمكن من إزالة تثبيت رسالة الجلسة: {e}")
                except Exception as e:
                    logger.error(f"خطأ في تحديث رسالة إنهاء الجلسة: {e}")
            
            # إرسال رسالة تأكيد للمشاركين
            for user_id in session.participants:
                try:
                    await bot.send_message(
                        chat_id=user_id,
                        text="📌 <b>انتهت حصتكم، أحسنتم 👏</b>\nاستمروا في التقدم!"
                    )
                except Exception as e:
                    logger.warning(f"لم أتمكن من إرسال رسالة إنهاء للمستخدم {user_id}: {e}")
            
            await callback_query.answer("✅ تم إنهاء الجلسة بنجاح!", show_alert=True)
        else:
            await callback_query.answer("❌ الجلسة غير موجودة.", show_alert=True)
    except Exception as e:
        await handle_error(e, "end_session_callback")
        await callback_query.answer("حدث خطأ، يرجى المحاولة مرة أخرى.", show_alert=True)

@router.callback_query(F.data.startswith("session_status_"))
async def session_status(callback_query: CallbackQuery):
    """عرض حالة الجلسة"""
    try:
        session_id = callback_query.data.split("_", 2)[2]
        
        if session_id not in group_sessions:
            await callback_query.answer("❌ الجلسة غير موجودة.", show_alert=True)
            return
        
        session = group_sessions[session_id]
        participant_count = len(session.participants)
        participant_list = "\n".join([f"• {p['name']}" for p in session.participants.values()]) if session.participants else "لا أحد بعد"
        
        status_text = "🟢 نشطة" if session.is_active else "🔴 منتهية"
        
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⏹️ إنهاء الجلسة", callback_data=f"end_session_{session_id}")],
            [InlineKeyboardButton(text="🔙 رجوع", callback_data=f"back_to_session_{session_id}")]
        ])
        
        await callback_query.message.edit_text(
            f"📊 <b>حالة الجلسة</b>\n"
            f"🆔 <b>معرف الجلسة:</b> {session_id[:20]}...\n"
            f"🕒 <b>الوقت المتبقي:</b> {format_time(session.time_left)}\n"
            f"👥 <b>عدد المشاركين:</b> {participant_count}\n"
            f"📊 <b>الحالة:</b> {status_text}\n"
            f"⏰ <b>آخر تحديث:</b> {session.last_update.strftime('%H:%M:%S')}\n\n"
            f"👥 <b>المشاركون:</b>\n{participant_list}",
            reply_markup=keyboard
        )
        await callback_query.answer()
    except Exception as e:
        await handle_error(e, "session_status")
        await callback_query.answer("حدث خطأ، يرجى المحاولة مرة أخرى.", show_alert=True)

# ===== مؤقت الجلسة =====
async def private_session_timer(session_id: str):
    """مؤقت الجلسة الخاصة"""
    try:
        while True:
            await asyncio.sleep(60)  # تحديث كل دقيقة
            
            if session_id not in group_sessions:
                break
                
            session = group_sessions[session_id]
            
            if not session.is_active:
                break
            
            # تحديث الوقت
            session.time_left -= 60
            session.last_update = datetime.now()
            
            # إنهاء الجلسة عند انتهاء الوقت
            if session.time_left <= 0:
                await end_private_session_automatically(session_id)
                break
    except Exception as e:
        logger.error(f"خطأ في مؤقت الجلسة الخاصة {session_id}: {e}")

async def group_session_timer(session_id: str):
    """مؤقت الجلسة الجماعية"""
    try:
        while True:
            await asyncio.sleep(60)  # تحديث كل دقيقة
            
            if session_id not in group_sessions:
                break
                
            session = group_sessions[session_id]
            
            if not session.is_active:
                break
            
            # تحديث الوقت
            session.time_left -= 60
            session.last_update = datetime.now()
            
            # إنهاء الجلسة عند انتهاء الوقت
            if session.time_left <= 0:
                await end_group_session_automatically(session_id)
                break
    except Exception as e:
        logger.error(f"خطأ في مؤقت الجلسة الجماعية {session_id}: {e}")

async def end_private_session_automatically(session_id: str):
    """إنهاء الجلسة الخاصة تلقائياً"""
    try:
        if session_id not in group_sessions:
            return
        
        session = group_sessions[session_id]
        session.is_active = False
        
        # إزالة من القوائم النشطة
        if session.chat_id in active_sessions:
            del active_sessions[session.chat_id]
        
        # إرسال رسالة انتهاء الجلسة
        try:
            await bot.send_message(
                chat_id=session.chat_id,
                text="☕ <b>خذ استراحتك يا محارب، حلمك على بعد خطوات!</b>"
            )
        except Exception as e:
            logger.error(f"خطأ في إرسال رسالة انتهاء الجلسة: {e}")
    except Exception as e:
        logger.error(f"خطأ في إنهاء الجلسة الخاصة تلقائياً {session_id}: {e}")

async def end_group_session_automatically(session_id: str):
    """إنهاء الجلسة الجماعية تلقائياً"""
    try:
        if session_id not in group_sessions:
            return
        
        session = group_sessions[session_id]
        session.is_active = False
        
        # إزالة من القوائم النشطة
        if session.chat_id in active_sessions:
            del active_sessions[session.chat_id]
        
        # تحديث رسالة الجلسة
        if session.message_id:
            participant_count = len(session.participants)
            participant_list = "\n".join([f"• {p['name']}" for p in session.participants.values()]) if session.participants else "لا أحد"
            
            try:
                await bot.edit_message_caption(
                    chat_id=session.chat_id,
                    message_id=session.message_id,
                    caption=(
                        f"✅ <b>انتهت الجلسة!</b>\n"
                        f"🕒 <b>المدة:</b> 55 دقيقة\n"
                        f"👤 <b>المؤسس:</b> {session.creator_name}\n\n"
                        f"👥 <b>المشاركون ({participant_count}):</b>\n{participant_list}\n\n"
                        f"☕ <b>استراحة مريحة!</b>\n"
                        f"استمر في التقدم، فأنت على الطريق الصحيح نحو النجاح!"
                    ),
                    reply_markup=None
                )
                
                # إزالة التثبيت
                if session.is_pinned:
                    try:
                        await bot(UnpinChatMessage(
                            chat_id=session.chat_id,
                            message_id=session.message_id
                        ))
                    except Exception as e:
                        logger.warning(f"لم أتمكن من إزالة تثبيت رسالة الجلسة: {e}")
            except Exception as e:
                logger.error(f"خطأ في تحديث رسالة انتهاء الجلسة: {e}")
        
        # إرسال رسائل الاستراحة للمشاركين
        for user_id in session.participants:
            try:
                await bot.send_message(
                    chat_id=user_id,
                    text="☕ <b>خذ استراحتك يا محارب، حلمك على بعد خطوات!</b>"
                )
            except Exception as e:
                logger.warning(f"لم أتمكن من إرسال رسالة استراحة للمستخدم {user_id}: {e}")
    except Exception as e:
        logger.error(f"خطأ في إنهاء الجلسة الجماعية تلقائياً {session_id}: {e}")

# ===== معالجات تمديد الجلسة =====
@router.callback_query(F.data.startswith("extend_session_"))
async def extend_session(callback_query: CallbackQuery):
    """تمديد الجلسة"""
    try:
        data_parts = callback_query.data.split("_")
        session_id = data_parts[2]
        user_id = int(data_parts[3])
        
        # التحقق من المستخدم
        if callback_query.from_user.id != user_id:
            await callback_query.answer("❌ هذا الزر ليس لك!", show_alert=True)
            return
        
        # التحقق من الجلسة
        if session_id not in group_sessions:
            await callback_query.message.answer("❌ الجلسة غير موجودة أو انتهت.")
            return
        
        session = group_sessions[session_id]
        
        # تحديث الوقت
        session.time_left = 55 * 60
        session.stats["extensions"] += 1
        
        # إرسال تأكيد
        try:
            await bot.send_message(
                chat_id=user_id,
                text=(
                    f"🚀 <b>جلسة جديدة!</b>\n"
                    f"بدأت جلستك الآن لمدة 55 دقيقة أخرى.\n\n"
                    f"🎯 استمر في التقدم!"
                ),
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="🌐 فتح الموقع", web_app=WebAppInfo(url=WEBSITE_URL))]
                ])
            )
        except Exception as e:
            logger.warning(f"لم أتمكن من إرسال رسالة تمديد للمستخدم {user_id}: {e}")
        
        await callback_query.answer("✅ تم تمديد الجلسة!", show_alert=True)
    except Exception as e:
        await handle_error(e, "extend_session")
        await callback_query.answer("حدث خطأ، يرجى المحاولة مرة أخرى.", show_alert=True)

@router.callback_query(F.data.startswith("end_session_user_"))
async def end_session_user(callback_query: CallbackQuery):
    """إنهاء الجلسة من قبل المستخدم"""
    try:
        data_parts = callback_query.data.split("_")
        session_id = data_parts[3]
        user_id = int(data_parts[4])
        
        # التحقق من المستخدم
        if callback_query.from_user.id != user_id:
            await callback_query.answer("❌ هذا الزر ليس لك!", show_alert=True)
            return
        
        await callback_query.answer("✅ تم إنهاء جلستك.", show_alert=True)
        
        # إرسال رسالة تأكيد
        try:
            await bot.send_message(
                chat_id=user_id,
                text="📌 <b>انتهت حصتك، أحسنت 👏</b>\nاستمر في التقدم!"
            )
        except Exception as e:
            logger.warning(f"لم أتمكن من إرسال رسالة إنهاء للمستخدم {user_id}: {e}")
    except Exception as e:
        await handle_error(e, "end_session_user")
        await callback_query.answer("حدث خطأ، يرجى المحاولة مرة أخرى.", show_alert=True)

# ===== إدارة الأخطاء =====
@router.errors()
async def error_handler(exception: Exception):
    """معالجة الأخطاء العامة"""
    logger.error(f"حدث خطأ غير متوقع: {exception}")
    # يمكن إضافة إرسال تنبيه للمطور هنا

# ===== تشغيل البوت =====
async def main():
    """الدالة الرئيسية لتشغيل البوت"""
    logger.info("🚀 بدء تشغيل بوت الدراسة الذكي...")
    
    # إرسال رسالة بدء للمطور (اختياري)
    try:
        # يمكنك إضافة معرف المطور هنا لإرسال تنبيه بالبدء
        # await bot.send_message(chat_id=DEVELOPER_ID, text="🚀 بدء تشغيل البوت")
        pass
    except Exception as e:
        logger.warning(f"لم أتمكن من إرسال رسالة بدء للمطور: {e}")
    
    # بدء الاستقبال
    await dp.start_polling(bot)

if __name__ == "__main__":
    # تشغيل البوت

    asyncio.run(main())

