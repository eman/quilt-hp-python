# gRPC services and method matrix

This table lists every RPC method in the Quilt API proto definitions, along with its request and response types and what (if anything) the library does with it.

## HomeDatastoreService

Defined in `quilt_hds.proto`. Package: `core.protos.home_datastore`.

| Method | Request | Response | Library wrapper |
| --- | --- | --- | --- |
| `GetHomeDatastoreSystem` | `GetHomeDatastoreSystemRequest` | `HomeDatastoreSystem` | `HomeDatastoreService.get_system()` → `SystemSnapshot` |
| `UpdateSpace` | `UpdateSpaceRequest` | `Space` | `HomeDatastoreService.update_space()` and `update_space_settings()` → `Space` |
| `UpdateIndoorUnit` | `UpdateIndoorUnitRequest` | `IndoorUnit` | `HomeDatastoreService.update_indoor_unit()` and `update_indoor_unit_settings()` → `IndoorUnit` |
| `UpdateComfortSetting` | `UpdateComfortSettingRequest` | `ComfortSetting` | `HomeDatastoreService.update_comfort_setting()` → `ComfortSetting` |
| `CreateScheduleDay` | `CreateScheduleDayRequest` | `ScheduleDay` | `HomeDatastoreService.create_schedule_day()` → `ScheduleDay` |
| `UpdateScheduleDay` | `UpdateScheduleDayRequest` | `ScheduleDay` | `HomeDatastoreService.update_schedule_day()` → `ScheduleDay` |
| `DeleteScheduleDay` | `DeleteScheduleDayRequest` | `Empty` | `HomeDatastoreService.delete_schedule_day()` |
| `CreateScheduleWeek` | `CreateScheduleWeekRequest` | `ScheduleWeek` | `HomeDatastoreService.create_schedule_week()` → `ScheduleWeek` |
| `UpdateScheduleWeek` | `UpdateScheduleWeekRequest` | `ScheduleWeek` | `HomeDatastoreService.update_schedule_week()` → `ScheduleWeek` |
| `DeleteScheduleWeek` | `DeleteScheduleWeekRequest` | `Empty` | `HomeDatastoreService.delete_schedule_week()` |
| `UpdateLocation` | `UpdateLocationRequest` | `Location` | `HomeDatastoreService.update_location_schedule_execution()`; pauses/resumes schedules |

## SystemInformationService

Defined in `quilt_services.proto`. Package: `core.protos.app`.

| Method | Request | Response | Library wrapper |
| --- | --- | --- | --- |
| `ListSystems` | `ListSystemInformationRequest` | `ListSystemInformationResponse` | `SystemInformationService.list_systems()` → `list[SystemInfo]` |
| `GetEnergyMetrics` | `GetEnergyMetricsRequest` | `GetEnergyMetricsResponse` | `SystemInformationService.get_energy_metrics()` → `list[SpaceEnergyMetrics]` |
| `SetAddress` | `SetAddressRequest` | `SetAddressResponse` | Not wrapped |

## UserService

Defined in `quilt_services.proto`. Package: `core.protos.app`.

| Method | Request | Response | Library wrapper |
| --- | --- | --- | --- |
| `GetLoggedInUser` | `GetLoggedInUserRequest` | `GetLoggedInUserResponse` | `UserService.get_current_user()` → `User` |
| `UpdateLoggedInUser` | `UpdateLoggedInUserRequest` | `UpdateLoggedInUserResponse` | `UserService.update_current_user()` → `User` |
| `GetUserAttributes` | `GetUserAttributesRequest` | `UserAttributes` | `UserService.get_user_attributes()` → `UserAttributes` |
| `PatchUserAttributes` | `PatchUserAttributesRequest` | `UserAttributes` | `UserService.patch_user_attributes()` → `UserAttributes` |

## NotifierService

Defined in `quilt_notifier.proto`. Package: `core.protos.notifier`.

| Method | Request | Response | Stream type | Library wrapper |
| --- | --- | --- | --- | --- |
| `Subscribe` | `stream SubscribeRequest` | `stream SubscribeResponse` | Bidirectional | `NotifierStream`; full lifecycle management |

## InvitationService

Defined in `quilt_services.proto`. Not currently wrapped by the library.

| Method | Request | Response |
| --- | --- | --- |
| `ListPendingInvitationsForLoggedInUser` | `ListPendingInvitationsRequest` | `ListPendingInvitationsResponse` |
| `CreateInvitation` | `CreateInvitationRequest` | `CreateInvitationResponse` |
| `AcceptInvitation` | `AcceptInvitationRequest` | `AcceptInvitationResponse` |
| `RejectInvitation` | `RejectInvitationRequest` | `RejectInvitationResponse` |
| `CancelInvitation` | `CancelInvitationRequest` | `CancelInvitationResponse` |
| `SendNotificationForInvitation` | `SendNotificationForInvitationRequest` | `SendNotificationForInvitationResponse` |

## PartnerService

Defined in `quilt_services.proto`. iOS/KMP + live-capture only; absent from current Android APK. Not wrapped.

| Method | Request | Response |
| --- | --- | --- |
| `InviteSystemOwner` | `InviteSystemOwnerRequest` | `InviteSystemOwnerResponse` |
| `GetLoggedInUserPartnerDetails` | `GetLoggedInUserPartnerDetailsRequest` | `GetLoggedInUserPartnerDetailsResponse` |
| `JoinPartnerOrganization` | `JoinPartnerOrganizationRequest` | `JoinPartnerOrganizationResponse` |
| `LeavePartnerOrganization` | `LeavePartnerOrganizationRequest` | `LeavePartnerOrganizationResponse` |

## SystemUserService

Defined in `quilt_services.proto`. Not currently wrapped by the library.

| Method | Request | Response |
| --- | --- | --- |
| `ListSystemUsers` | `ListSystemUsersRequest` | `ListSystemUsersResponse` |
| `GetRoleOfLoggedInSystemUser` | `GetRoleOfLoggedInSystemUserRequest` | `GetRoleOfLoggedInSystemUserResponse` |
| `RemoveSystemUser` | `RemoveSystemUserRequest` | `RemoveSystemUserResponse` |
| `RemoveLoggedInSystemUser` | `RemoveLoggedInSystemUserRequest` | `RemoveLoggedInSystemUserResponse` |
| `ChangeRoleOfSystemUser` | `ChangeRoleOfSystemUserRequest` | `ChangeRoleOfSystemUserResponse` |

## DevicePairingService

Defined in `quilt_device_pairing.proto`. Not currently wrapped by the library.

## SystemService

Defined in `quilt_system.proto`. Package: `core.protos.system`. Not currently wrapped by the library.

## MobileAppService

Defined in `quilt_services.proto`. Contains `AuthorizeNewDevice`. Not currently wrapped by the library.
