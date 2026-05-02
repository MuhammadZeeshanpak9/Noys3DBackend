from pydantic import BaseModel, EmailStr, Field
from typing import Optional, List
from datetime import datetime
from uuid import UUID
from enum import Enum


class UserRole(str, Enum):
    USER = "user"
    ADMIN = "admin"


class SubscriptionPlan(str, Enum):
    STARTER = "starter"
    BRONZE = "bronze"
    SILVER = "silver"
    GOLD = "gold"


class OrderStatus(str, Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    SHIPPED = "shipped"
    DELIVERED = "delivered"
    CANCELLED = "cancelled"

class UserCreate(BaseModel):
    email: EmailStr
    password: str = Field(..., min_length=6)
    name: str


class UserLogin(BaseModel):
    email: EmailStr
    password: str


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"


class UserResponse(BaseModel):
    id: UUID
    email: str
    name: str
    role: UserRole
    credits: int
    subscription_plan: Optional[SubscriptionPlan] = None
    avatar_url: Optional[str] = None
    created_at: datetime

    class Config:
        from_attributes = True


class UserUpdate(BaseModel):
    name: Optional[str] = None
    avatar_url: Optional[str] = None

class CategoryCreate(BaseModel):
    name: str
    slug: str
    description: Optional[str] = None


class CategoryResponse(BaseModel):
    id: UUID
    name: str
    slug: str
    description: Optional[str] = None
    created_at: datetime

    class Config:
        from_attributes = True


class CategoryUpdate(BaseModel):
    name: Optional[str] = None
    slug: Optional[str] = None
    description: Optional[str] = None

class ProductCreate(BaseModel):
    name: str
    description: Optional[str] = None
    price: float = Field(..., gt=0)
    image_url: Optional[str] = None
    category_id: Optional[UUID] = None
    is_active: bool = True


class ProductResponse(BaseModel):
    id: UUID
    name: str
    description: Optional[str] = None
    price: float
    image_url: Optional[str] = None
    category_id: Optional[UUID] = None
    is_active: bool
    created_at: datetime

    class Config:
        from_attributes = True


class ProductUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    price: Optional[float] = None
    image_url: Optional[str] = None
    category_id: Optional[UUID] = None
    is_active: Optional[bool] = None

class PlanCreate(BaseModel):
    name: str
    price: float = Field(..., gt=0)
    credits: int = Field(..., gt=0)
    features: List[str] = []
    is_popular: bool = False
    stripe_price_id: Optional[str] = None


class PlanResponse(BaseModel):
    id: UUID
    name: str
    price: float
    credits: int
    features: List[str]
    is_popular: bool
    stripe_price_id: Optional[str] = None
    created_at: datetime

    class Config:
        from_attributes = True


class PlanUpdate(BaseModel):
    name: Optional[str] = None
    price: Optional[float] = None
    credits: Optional[int] = None
    features: Optional[List[str]] = None
    is_popular: Optional[bool] = None
    stripe_price_id: Optional[str] = None

class CreditPackCreate(BaseModel):
    credits: int = Field(..., gt=0)
    price: float = Field(..., gt=0)
    stripe_price_id: Optional[str] = None
    is_active: bool = True


class CreditPackResponse(BaseModel):
    id: UUID
    credits: int
    price: float
    stripe_price_id: Optional[str] = None
    is_active: bool
    created_at: datetime

    class Config:
        from_attributes = True


class CreditPackUpdate(BaseModel):
    credits: Optional[int] = None
    price: Optional[float] = None
    stripe_price_id: Optional[str] = None
    is_active: Optional[bool] = None

class ShippingAddress(BaseModel):
    first_name: str
    last_name: str
    email: EmailStr
    address: str
    city: str
    zip_code: str


class OrderItemCreate(BaseModel):
    id: str
    name: str
    price: float
    quantity: int = Field(..., gt=0)
    image: Optional[str] = None


class OrderCreate(BaseModel):
    items: List[OrderItemCreate]
    shipping_address: ShippingAddress


class OrderResponse(BaseModel):
    id: UUID
    user_id: UUID
    items: List[dict]
    total: float
    status: OrderStatus
    shipping_address: dict
    created_at: datetime

    class Config:
        from_attributes = True

class GenerationCreate(BaseModel):
    prompt: str
    images: Optional[List[str]] = None


class GenerationResponse(BaseModel):
    id: UUID
    user_id: UUID
    prompt: str
    image_url: Optional[str] = None
    stl_url: Optional[str] = None
    is_saved: bool
    credits_used: int
    created_at: datetime

    class Config:
        from_attributes = True

class PaymentCreate(BaseModel):
    type: str  # subscription, credits
    plan_id: Optional[UUID] = None
    credit_pack_id: Optional[UUID] = None


class PaymentResponse(BaseModel):
    id: UUID
    user_id: UUID
    type: str
    amount: float
    status: str
    stripe_payment_intent_id: Optional[str] = None
    created_at: datetime

    class Config:
        from_attributes = True

class AdminStats(BaseModel):
    total_users: int
    total_orders: int
    total_revenue: float
    active_subscriptions: int
    total_credits_used: int
