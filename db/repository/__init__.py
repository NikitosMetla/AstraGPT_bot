from .admin_repo import AdminRepository
from .ai_requests_repo import AiRequestsRepository
from .dialogs_messages_repo import DialogsMessagesRepository
from .events_repo import EventsRepository
from .generations_packets_repository import GenerationsPacketsRepository
from .notifications_repository import NotificationsRepository
from .operations_repo import OperationRepository
from .subscriptions_repo import SubscriptionsRepository
from .type_subscriptions_repository import TypeSubscriptionsRepository
from .users_repo import UserRepository
from .refferal_repo import ReferralSystemRepository
from .promo_activations_repo import PromoActivationsRepository
from .video_generations_packets_repo import VideoVideoGenerationsPacketsRepository

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
generations_packets_repository = GenerationsPacketsRepository()
dialogs_messages_repository = DialogsMessagesRepository()
video_generations_packets_repository = VideoVideoGenerationsPacketsRepository()

__all__ = ['users_repository',
           'admin_repository',
           'ai_requests_repository',
           'subscriptions_repository',
           'referral_system_repository',
           'promo_activations_repository',
           'events_repository',
           'notifications_repository',
           'operation_repository',
           'type_subscriptions_repository',
           'generations_packets_repository',
           'dialogs_messages_repository',
           'video_generations_packets_repository',
          ]