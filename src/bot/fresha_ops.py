"""Fresha dashboard GraphQL operations, verbatim from the 2026-10-20 recording.

Generated from .local/fresha-ops.json by hand; do not edit the query texts,
Fresha accepts them exactly as its own web app sends them. One exception:
CustomerOverviewUpcomingAppointmentQuery had `first: 1` written into the
text; it takes a `$first` variable here (checked live 2026-10-21). Each entry
is (kind, operationName, query) where kind is "query" or "mutation".
"""

OPS = {
    "availableTimeSlots": ("query", "availableTimeSlots", """query availableTimeSlots($input: Scheduling_AvailableTimeSlotsInput!, $withAttendees: Boolean!) {
  __typename
  availableTimeSlots: Scheduling_availableTimeSlots(input: $input) {
    __typename
    dailyAvailableTimeSlots {
      __typename
      date
      closed
      locationId
      possibleOffers {
        __typename
        startTime
        attendees @include(if: $withAttendees) {
          __typename
          offerItems {
            __typename
            offerItemPosition
            startTime
            itemDetails {
              __typename
              ... on Scheduling_ServicePricingLevel {
                __typename
                servicePricingLevelId
                resourceId
                resourceIds
                employeeId
              }
              ... on Scheduling_PackageItem {
                __typename
                packageItemId
                resourceId
                resourceIds
                employeeId
              }
            }
          }
        }
      }
    }
  }
}"""),
    "SchedulingConflicts": ("query", "SchedulingConflicts", """query SchedulingConflicts($input: Scheduling_SchedulingConflictsInput!) {
  __typename
  schedulingConflicts: Scheduling_schedulingConflicts(input: $input) {
    __typename
    scheduledItemsConflicts {
      __typename
      conflicts {
        __typename
        ... on Scheduling_EmployeeHasExistingAppointmentConflict {
          __typename
          conflictType
          employeeId
          existingAppointmentId
          existingBookingId
        }
        ... on Scheduling_EmployeeHasExistingBlockedTimeConflict {
          __typename
          conflictType
          employeeId
          existingBlockedTimeId
        }
        ... on Scheduling_EmployeeNotAssignedToServiceConflict {
          __typename
          conflictType
          employeeId
          servicePricingLevelId
        }
        ... on Scheduling_OutsideEmployeeScheduleConflict {
          __typename
          conflictType
          employeeId
        }
        ... on Scheduling_ResourceHasExistingAppointmentConflict {
          __typename
          conflictType
          existingAppointmentIds
          existingBookingIds
          resourceId
        }
        ... on Scheduling_ResourceHasExistingBlockedTimeConflict {
          __typename
          conflictType
          existingBlockedTimeId
          resourceId
        }
        ... on Scheduling_ResourceNotAssignedToServiceConflict {
          __typename
          conflictType
          resourceId
          servicePricingLevelId
        }
        ... on Scheduling_OutsideResourceScheduleConflict {
          __typename
          conflictType
          resourceId
        }
        ... on Scheduling_OutsideServiceScheduleConflict {
          __typename
          conflictType
          serviceId
          servicePricingLevelId
        }
        ... on Scheduling_ResourceRequestedOverCapacityConflict {
          __typename
          conflictType
          resourceId
        }
        ... on Scheduling_ResourceBlockedByLinkedResourceConflict {
          __typename
          conflictType
          resourceId
          linkedResourceId
          existingAppointmentIds
          existingBookingIds
        }
      }
      scheduledItemId
    }
  }
}"""),
    "appointment_calculateAppointmentProtectionFees": ("query", "appointment_calculateAppointmentProtectionFees", """query appointment_calculateAppointmentProtectionFees($input: AppointmentProtection_CalculateAppointmentProtectionFeesInput!) {
  __typename
  calculateAppointmentProtectionFees: AppointmentProtection_calculateAppointmentProtectionFees(
    input: $input
  ) {
    __typename
    protectedBaseAmount
    depositAmount
    cancellationFeeAmount
    noShowFeeAmount
    strategy
  }
}"""),
    "createAppointmentByEmployee": ("mutation", "createAppointmentByEmployee", """mutation createAppointmentByEmployee($input: AppointmentsManager_CreateAppointmentByEmployeeInput!) {
  __typename
  AppointmentsManager_createAppointmentByEmployee(input: $input) {
    __typename
    appointment {
      __typename
      id
    }
    primaryBookingId
    warnings {
      __typename
      message
    }
  }
}"""),
    "viewAppointment": ("query", "viewAppointment", """query viewAppointment($id: ID!) {
  __typename
  appointment: Appointments_appointment(id: $id) {
    __typename
    id
    version
    createdAt
    primaryBookingId
    customer {
      __typename
      id
      firstName
    }
    customerId
    locationId
    isOnline
    purchaseOrderId
    salesOrderId
    safetyStatus
    status
    statusLabel {
      __typename
      id
      isCustom
    }
    startWallClock
    groupAppointment {
      __typename
      groupId
      ownerId
    }
    recurrenceSettings {
      __typename
      id
      intervalBase
      intervalMultiplier
      endCondition {
        __typename
        ... on Appointments_RecurrenceEndByDate {
          __typename
          endsAt
        }
        ... on Appointments_RecurrenceEndByOccurrences {
          __typename
          endsAt
          occurrences
        }
      }
    }
    bookings {
      __typename
      id
      serviceId
      service {
        __typename
        id
        name
        patchTestRequired
        employeeRequired
        roomRequired
        serviceGroup {
          __typename
          appointmentColor
        }
        servicePricingLevels {
          __typename
          id
          name
        }
      }
      servicePricingLevelId
      purchaseOrderItemId
      startWallClock
      employees {
        __typename
        id
        isRequested
        genderRequested
        employee {
          __typename
          id
          fullName
        }
      }
      resources {
        __typename
        id
      }
      bookingTimeSegments {
        __typename
        id
        durationInSeconds
        durationType
        isMainServicingTime
        sortingId
        totalDurationInSeconds
      }
      bookingServiceAddOns {
        __typename
        id
        serviceAddOnId
        serviceAddOn {
          __typename
          name
        }
        durationInSeconds
        quantity
        purchaseOrderItemId
      }
      bookingBundleItem {
        __typename
        id
        bundleInstanceId
        bundleItemId
        bundleVersionId
        bundleVersion {
          __typename
          id
          name
          outdated
          retailPrice
          pricingType
          percentageDiscount
          package {
            __typename
            id
          }
        }
      }
    }
  }
}"""),
    "CustomerOverviewUpcomingAppointmentQuery": ("query", "CustomerOverviewUpcomingAppointmentQuery", """query CustomerOverviewUpcomingAppointmentQuery($customerId: ID!, $first: Int!) {
  __typename
  appointments: Appointments_appointments(
    first: $first
    customerId: $customerId
    onlyFuture: true
    order: {field: START_DATETIME, direction: ASC}
  ) {
    __typename
    edges {
      __typename
      node {
        __typename
        ...CustomerAppointmentCard
      }
      cursor
    }
  }
}
fragment CustomerAppointmentCard on Appointments_Appointment {
  __typename
  id
  status
  statusLabelId
  startWallClock
  locationId
  primaryBookingId
  salesOrderId
  customerId
  preferredNote {
    __typename
    note {
      __typename
      id
      legacyRef
      body
      attachments {
        __typename
        id
      }
    }
    totalNoteCount
  }
  consultationForms {
    __typename
    id
    status
  }
  bookings {
    __typename
    id
    priceType
    price
    startWallClock
    startDatetime
    endDatetime
    orderItem {
      __typename
      salePrice
      quantity
    }
    bookingServiceAddOns {
      __typename
      serviceAddOnId
      orderItem {
        __typename
        quantity
        salePrice
      }
      serviceAddOn {
        __typename
        name
      }
    }
    servicePricingLevelId
    service {
      __typename
      name
      servicePricingLevels {
        __typename
        id
        name
      }
    }
    employee {
      __typename
      firstName
      lastName
    }
  }
}"""),
    "initializeAppointmentProtectionEnforcement": ("mutation", "initializeAppointmentProtectionEnforcement", """mutation initializeAppointmentProtectionEnforcement($input: AppointmentProtection_InitializeAppointmentProtectionEnforcementInput!) {
  __typename
  initializeAppointmentProtectionEnforcement: AppointmentProtection_initializeAppointmentProtectionEnforcement(
    input: $input
  ) {
    __typename
    appointmentProtectionEnforcement {
      __typename
      ...AppointmentProtectionEnforcementFragment
    }
    paymentMethods {
      __typename
      ...AppointmentProtectionPaymentMethodFragment
    }
    intendedTransaction {
      __typename
      ...AppointmentProtectionIntendedTransactionFragment
    }
    intendedRefunds {
      __typename
      ...AppointmentProtectionIntendedTransactionFragment
    }
    deposits {
      __typename
      ...AppointmentProtectionDepositFragment
    }
    leftToPay
    isCustomAmountSupported
  }
}
fragment AppointmentProtectionEnforcementFragment on AppointmentProtection_AppointmentProtectionEnforcement {
  __typename
  originalProtectionAmount
  protectionAmount
  orderId
  cancellationReasonId
  action
  appointmentId
  hasPrepayment
}
fragment AppointmentProtectionPaymentMethodFragment on AppointmentProtection_PaymentMethod {
  __typename
  id
  type
  metadata {
    __typename
    ... on AppointmentProtection_FreshaCreditPaymentMethodMetadata {
      __typename
      balance
    }
    ... on AppointmentProtection_FreshaPayPaymentMethodMetadata {
      __typename
      bankCard {
        __typename
        brand
        last4
        expYear
        expMonth
      }
    }
    ... on AppointmentProtection_GiftCardPaymentMethodMetadata {
      __typename
      giftCards {
        __typename
        id
        code
        remainingValue
      }
    }
  }
}
fragment AppointmentProtectionIntendedTransactionFragment on AppointmentProtection_IntendedTransaction {
  __typename
  amount
  paymentMethodId
  paymentMethodType
  paymentMethodMetadata {
    __typename
    ... on AppointmentProtection_IntendedTransactionGiftCardPaymentMethodMetadata {
      __typename
      giftCardId
    }
  }
}
fragment AppointmentProtectionDepositFragment on AppointmentProtection_Deposit {
  __typename
  amount
  collectedPaymentType
  collectedPayment {
    __typename
    ... on AppointmentProtection_DepositBankCardCollectedPayment {
      __typename
      brand
      last4
    }
    ... on AppointmentProtection_DepositGiftCardCollectedPayment {
      __typename
      code
    }
    ... on AppointmentProtection_DepositIdealCollectedPayment {
      __typename
      bankName
      bankBic
      ibanLast4
    }
  }
  paymentInstrument {
    __typename
    instrument
    hint
    displayBrand
  }
}"""),
    "cancelAppointmentWithNoCharge": ("mutation", "cancelAppointmentWithNoCharge", """mutation cancelAppointmentWithNoCharge($input: AppointmentProtection_CancelAppointmentWithNoChargeInput!) {
  __typename
  cancelAppointmentWithNoCharge: AppointmentProtection_cancelAppointmentWithNoCharge(
    input: $input
  ) {
    __typename
    appointmentId
  }
}"""),
    "pricingCatalogList": ("query", "pricingCatalogList", """query pricingCatalogList($locationId: ID!, $first: Int!, $after: String, $filters: Pricing_CatalogFiltersInput, $autoSelectedPriceModifiers: [Pricing_CatalogAutoSelectedPriceModifierInput!], $customerId: ID, $currentBasket: Pricing_BasketInput, $bookingStartTime: Pricing_WallClockDateAndTimeInput) {
  __typename
  catalog: Pricing_catalog(
    locationId: $locationId
    itemType: SERVICE_AND_BUNDLE
    first: $first
    after: $after
    filters: $filters
    autoSelectedPriceModifiers: $autoSelectedPriceModifiers
    customerId: $customerId
    currentBasket: $currentBasket
    bookingStartTime: $bookingStartTime
  ) {
    __typename
    pageInfo {
      __typename
      hasNextPage
      endCursor
    }
    categories {
      __typename
      id
      name
      color
    }
    edges {
      __typename
      node {
        __typename
        ... on Pricing_CatalogService {
          __typename
          id
          categoryId
          name
          employeeIds
          assignedEmployeePerformsService
          isEmployeeRequired
          isPatchTestRequired
          resourceRequirement {
            __typename
            resourceIds
          }
          servicePricingLevels {
            __typename
            id
            name
            minDurationInSeconds
            maxDurationInSeconds
            price {
              __typename
              listPrice
              salePrice
              priceType
              priceModifiers {
                __typename
                id
                name
                shortName
                delta
                type
                rewardSource
              }
            }
            timeSegments {
              __typename
              durationType
              minDurationInSeconds
              maxDurationInSeconds
              isMainServicingTime
            }
          }
        }
        ... on Pricing_CatalogBundle {
          __typename
          bundleId
          versionId
          categoryId
          name
          listPrice
          salePrice
          minDurationInSeconds
          maxDurationInSeconds
          scheduleType
          bundleItems {
            __typename
            id
            employeeIds
            assignedEmployeePerformsService
            hasServiceAddOns
            servicePricingLevelId
          }
        }
      }
    }
  }
}"""),
    "appointmentCatalogItemsWithAssignments": ("query", "appointmentCatalogItemsWithAssignments", """query appointmentCatalogItemsWithAssignments($items: [Catalog_CatalogItemAssignmentInput!]!, $locationIds: [ID!]) {
  __typename
  catalogItemsWithAssignments: Partners_catalogItemsWithAssignments(
    items: $items
    locationIds: $locationIds
  ) {
    __typename
    servicePricingLevel {
      __typename
      id
      price
      priceType
      retailPrice
      retailPriceType
      minDurationInSeconds
      maxDurationInSeconds
      totalMinDurationInSeconds
      totalMaxDurationInSeconds
      name
      serviceTimeSegments {
        __typename
        durationType
        durationInSeconds
        isMainServicingTime
        sortingId
        maxDurationInSeconds
        minDurationInSeconds
      }
      service {
        __typename
        id
        name
        roomRequired
        employeeRequired
        rooms {
          __typename
          id
          location {
            __typename
            id
          }
          name
        }
        patchTestRequired
        isResourceRequiredForProcessingTime
        isResourceRequiredForBlockedTime
        serviceGroup {
          __typename
          appointmentColor
        }
        serviceResourceRequirements {
          __typename
          locationId
          resourceIds
        }
      }
    }
    packageVersion {
      __typename
      id
      name
      type
      nonDiscountedPrice
      retailPrice
      retailPriceType
      pricingType
      percentageDiscount
      package {
        __typename
        id
      }
      items {
        __typename
        id
        sortingId
        minDurationInSeconds
        maxDurationInSeconds
        totalMinDurationInSeconds
        totalMaxDurationInSeconds
        discountedRetailPrice
        retailPrice
        retailPriceType
        packageTimeSegments {
          __typename
          durationType
          durationInSeconds
          isMainServicingTime
          sortingId
          maxDurationInSeconds
          minDurationInSeconds
        }
        servicePricingLevel {
          __typename
          id
          price
          priceType
          name
          service {
            __typename
            id
            name
            roomRequired
            employeeRequired
            rooms {
              __typename
              id
              location {
                __typename
                id
              }
              name
            }
            patchTestRequired
            isResourceRequiredForProcessingTime
            isResourceRequiredForBlockedTime
            serviceGroup {
              __typename
              appointmentColor
            }
            serviceResourceRequirements {
              __typename
              locationId
              resourceIds
            }
          }
        }
      }
    }
  }
}"""),
}


# The client profile page in one call, for the client mirror (clients/sync.py).
# Composed 2026-10-24 from the queries the dashboard sends when a profile is
# opened (CustomerLeftDrawer, ListCustomerPatchTests, ListClientNotes,
# ListCustomerAttachments, CustomerUpcomingAppointmentQuery,
# CustomerPastAppointmentQuery): the same fields, under one operation name,
# so the sync makes one GraphQL request per client instead of six.
OPS["clientRecord"] = ("query", "clientRecord", """query clientRecord($customerId: ID!) {
  __typename
  customer: Customers_customer(id: $customerId) {
    __typename
    id
    firstName
    lastName
    fullName
    isBlocked
    blockReason
    birthdayDay
    birthdayMonth
    birthdayYear
    gender
    pronoun
    createdAt
    deletedAt
    staffAlert
    hasPaymentMethod
    patchTestCount
    onlineProfile {
      __typename
      isEmailVerified
      isPhoneVerified
    }
    labels {
      __typename
      edges {
        __typename
        node {
          __typename
          id
          ... on Customers_NoShowLabel {
            __typename
            count
          }
          ... on Customers_BirthdayLabel {
            __typename
            date
          }
          ... on Customers_UnpaidLabel {
            __typename
            amount
          }
        }
      }
    }
    tags(first: 50) {
      __typename
      edges {
        __typename
        node {
          __typename
          id
          name
          assignedAt
        }
      }
    }
    segmentBadges(first: 50) {
      __typename
      edges {
        __typename
        node {
          __typename
          id
          definition {
            __typename
            id
            badgeName
          }
        }
      }
    }
    allergies(first: 50) {
      __typename
      edges {
        __typename
        node {
          __typename
          id
          name
          severity
          type
          reaction
          description
        }
      }
    }
    patchTests(first: 50) {
      __typename
      edges {
        __typename
        node {
          __typename
          id
          title
          status
          performedDate
          isExpired
          createdAt
          confirmationRequired
          expirationDate
        }
      }
    }
  }
  notes: Notes_notes(customerId: $customerId, first: 50, includeClientNote: true, sort: ACTIVITY_DATE) {
    __typename
    edges {
      __typename
      node {
        __typename
        id
        body
        type
        createdAt
        lastEditedAt
        activityAt
        authorType
        author {
          __typename
          id
          fullName
        }
        authorClient {
          __typename
          id
          fullName
        }
        appointment {
          __typename
          id
          startDatetime
        }
        attachments {
          __typename
          id
          fileName
          kind
        }
      }
    }
    pageInfo {
      __typename
      hasNextPage
    }
  }
  attachments: Notes_attachmentsByCustomer(customerId: $customerId, first: 30) {
    __typename
    edges {
      __typename
      node {
        __typename
        id
        fileName
        contentType
        fileSizeBytes
        kind
        createdAt
      }
    }
  }
  upcoming: Appointments_appointments(customerId: $customerId, first: 20, onlyFuture: true, order: {field: START_DATETIME, direction: ASC}) {
    __typename
    edges {
      __typename
      node {
        __typename
        ...TlgAppointment
      }
    }
    pageInfo {
      __typename
      hasNextPage
    }
  }
  past: Appointments_appointments(customerId: $customerId, first: 50, onlyPast: true, order: {field: START_DATETIME, direction: DESC}) {
    __typename
    edges {
      __typename
      node {
        __typename
        ...TlgAppointment
      }
    }
    pageInfo {
      __typename
      hasNextPage
    }
  }
}
fragment TlgAppointment on Appointments_Appointment {
  __typename
  id
  status
  statusLabelId
  startWallClock
  primaryBookingId
  salesOrderId
  consultationForms {
    __typename
    id
    status
  }
  preferredNote {
    __typename
    note {
      __typename
      id
      body
    }
  }
  bookings {
    __typename
    id
    priceType
    price
    startWallClock
    endDatetime
    servicePricingLevelId
    service {
      __typename
      name
      servicePricingLevels {
        __typename
        id
        name
      }
    }
    employee {
      __typename
      firstName
      lastName
    }
    bookingServiceAddOns {
      __typename
      serviceAddOnId
      serviceAddOn {
        __typename
        name
      }
    }
  }
}
""")
