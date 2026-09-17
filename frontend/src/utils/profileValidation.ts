import type { UserProfile } from '@/types'

export type RequiredProfileField =
  | 'gender'
  | 'age'
  | 'height_cm'
  | 'weight_kg'
  | 'activity_level'
  | 'goal'

export type ProfileDraft = Pick<UserProfile, RequiredProfileField>
export type ProfileValidationErrors = Partial<Record<RequiredProfileField, string>>

export const PROFILE_REQUIRED_MESSAGES: Record<RequiredProfileField, string> = {
  gender: '请选择性别',
  age: '请输入年龄',
  height_cm: '请输入身高',
  weight_kg: '请输入体重',
  activity_level: '请选择活动水平',
  goal: '请选择目标',
}

export function getProfileValidationErrors(profile: ProfileDraft): ProfileValidationErrors {
  const errors: ProfileValidationErrors = {}

  for (const field of Object.keys(PROFILE_REQUIRED_MESSAGES) as RequiredProfileField[]) {
    const value = profile[field]
    if (value === null || value === undefined) {
      errors[field] = PROFILE_REQUIRED_MESSAGES[field]
    }
  }

  return errors
}
