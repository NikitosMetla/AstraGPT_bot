from .admin_repo import AdminRepository
from .ai_requests_repo import AiRequestsRepository
from .events_repo import EventsRepository
from .notifications_repository import NotificationsRepository
from .operations_repo import OperationRepository
from .subscriptions_repo import SubscriptionsRepository
from .type_subscriptions_repository import TypeSubscriptionsRepository
from .users_repo import UserRepository
from .refferal_repo import ReferralSystemRepository
from .promo_activations_repo import PromoActivationsRepository

users_repository = UserRepository()
admin_repository = AdminRepository()
ai_requests_repository = AiRequestsRepository()
subscriptions_repository = SubscriptionsRepository()
referral_system_repository = ReferralSystemRepository()
promo_activations_repository = PromoActivationsRepository()
events_repository = EventsRepository()
notifications_repository = NotificationsRepository()
operation_repository = OperationRepository()
type_subscriptions_repository = TypeSubscriptionsRepository()

__all__ = ['users_repository',
           'admin_repository',
           'ai_requests_repository',
           'subscriptions_repository',
           'referral_system_repository',
           'promo_activations_repository',
           'events_repository',
           'notifications_repository',
           'operation_repository',
           'type_subscriptions_repository'
          ]