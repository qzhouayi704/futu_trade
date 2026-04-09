// API 响应类型定义

export interface ApiResponse<T = any> {
  success: boolean;
  data?: T;
  message?: string;
  error_code?: string;
  status_code?: number;
  meta?: {
    page?: number;
    total_pages?: number;
    total?: number;
  };
  extra?: unknown;
}

export interface PaginatedResponse<T> extends ApiResponse<T[]> {
  pagination?: {
    page: number;
    page_size: number;
    total: number;
    total_pages: number;
  };
}

export interface ApiError {
  success: false;
  message: string;
  error_code?: string;
  status_code?: number;
}
