# from datetime import datetime, timedelta
# from typing import List
#
# from db.models import Users, AiRequests
#
#
# class Statistic:
#     def __init__(self,
#                  users: list | None = None,
#                  ai_requests: list | None = None,
#                  operations: list | None = None,
#                  photo_ai_requests: list | None = None):
#         self.users: List[Users] = users
#         self.ai_requests: List[AiRequests] = ai_requests
#         self.operations: List[Operations] = operations
#         self.photo_ai_requests: List[AiRequests] = photo_ai_requests
#
#     async def get_users_statistic_by_timedelta(self, time_delta: int):
#         if self.users is not None:
#             number_start = 0
#             number_finish = 0
#             current_datetime = datetime.now()
#             for user in self.users:
#                 if (current_datetime - user.creation_date) <= timedelta(days=time_delta):
#                     number_start += 1
#             return number_start
#
#     async def get_users_all_statistic(self):
#         if self.users is not None:
#             number_start = 0
#             number_finish = 0
#             return len(self.users)
#
#     async def get_ai_requests_statistic_by_timedelta(self, time_delta: int):
#         if self.ai_requests is not None:
#             number_start = 0
#             number_finish = 0
#             current_datetime = datetime.now()
#             for request in self.ai_requests:
#                 if (current_datetime - request.creation_date) <= timedelta(days=time_delta):
#                     number_start += 1
#             return number_start
#
#     async def get_ai_requests_all_statistic(self):
#         if self.ai_requests is not None:
#             number_start = 0
#             number_finish = 0
#             return len(self.ai_requests)
#
#     async def get_requests_with_photo_by_timedelta(self, time_delta: int):
#         if self.photo_ai_requests is not None:
#             number_start = 0
#             number_finish = 0
#             current_datetime = datetime.now()
#             for request in self.photo_ai_requests:
#                 if (current_datetime - request.creation_date) <= timedelta(days=time_delta) and request.has_photo:
#                     number_start += 1
#             return number_start
#
#     async def get_photo_ai_requests_all_statistic(self):
#         if self.photo_ai_requests is not None:
#             number_start = 0
#             number_finish = 0
#             return len(self.photo_ai_requests)
#
#     async def get_operations_statistic_by_timedelta(self, time_delta: int):
#         if self.operations is not None:
#             number_start = 0
#             number_finish = 0
#             current_datetime = datetime.now()
#             for operation in self.operations:
#                 if (current_datetime - operation.creation_date) <= timedelta(days=time_delta):
#                     number_start += 1
#                     if operation.is_paid:
#                         number_finish += 1
#             return [number_start, number_finish]
#
#     async def get_operations_all_statistic(self):
#         if self.operations is not None:
#             number_start = 0
#             number_finish = 0
#             for operation in self.operations:
#                 number_start += 1
#                 if operation.is_paid:
#                     number_finish += 1
#             return [number_start, number_finish]