import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import DataView from '../src/components/DataView.vue'
import ErrorBanner from '../src/components/ErrorBanner.vue'
import { PAGE_SIZE, flatten, hasNext, intParam, nextOffset, prevOffset } from '../src/lib'

describe('paging', () => {
  it('moves the offset by one page and never below zero', () => {
    expect(PAGE_SIZE).toBe(100)
    expect(prevOffset(0)).toBe(0)
    expect(prevOffset(100)).toBe(0)
    expect(prevOffset(250)).toBe(150)
    expect(nextOffset(100)).toBe(200)
  })
  it('enables next only while offset + 100 is below the total', () => {
    expect(hasNext(0, 150, 100)).toBe(true)
    expect(hasNext(100, 150, 50)).toBe(false)
    expect(hasNext(0, 100, 100)).toBe(false)
    expect(hasNext(0, undefined, 100)).toBe(true)
    expect(hasNext(0, undefined, 3)).toBe(false)
  })
  it('reads the offset from the hash query as a multiple of the page size', () => {
    expect(intParam(new URLSearchParams('offset=250'), 'offset', 0, 100)).toBe(200)
    expect(intParam(new URLSearchParams('offset=-5'), 'offset', 0, 100)).toBe(0)
    expect(intParam(new URLSearchParams('offset=abc'), 'offset', 0, 100)).toBe(0)
    expect(intParam(new URLSearchParams(''), 'page', 1)).toBe(1)
  })
})

describe('error banner', () => {
  it('shows the numeric code and the message verbatim', () => {
    const wrapper = mount(ErrorBanner, { props: { banner: { code: 503, message: 'SCAFFOLD_ONLY: the inventory is not ready' } } })
    const banner = wrapper.get('[data-testid=error-banner]')
    expect(banner.attributes('role')).toBe('alert')
    expect(wrapper.get('[data-testid=error-code]').text()).toBe('503')
    expect(wrapper.get('[data-testid=error-code]').attributes('data-raw')).toBe('503')
    expect(wrapper.get('[data-testid=error-message]').text()).toBe('SCAFFOLD_ONLY: the inventory is not ready')
  })
  it('renders nothing without an error', () => {
    expect(mount(ErrorBanner, { props: { banner: null } }).find('[data-testid=error-banner]').exists()).toBe(false)
  })
})

describe('no-demo-data', () => {
  it('renders nothing for no result', () => {
    expect(mount(DataView, { props: { data: null } }).html()).toBe('<!--v-if-->')
  })
  it('renders an empty state, never fixtures, for an empty list', () => {
    const wrapper = mount(DataView, { props: { data: { items: [], count: 0 }, rowTestId: 'snap-row' } })
    expect(wrapper.find('[data-testid=empty]').exists()).toBe(true)
    expect(wrapper.findAll('[data-testid=snap-row]')).toHaveLength(0)
    expect(wrapper.get('[data-field=count]').attributes('data-raw')).toBe('0')
  })
  it('renders exactly the rows and raw values of the result', () => {
    const data = { total: 2, items: [{ path: 'a/b.txt', type: 'file', size: 1536 }, { path: 'a', type: 'dir' }] }
    const wrapper = mount(DataView, { props: { data, rowTestId: 'file-row' } })
    expect(wrapper.findAll('[data-testid=file-row]')).toHaveLength(2)
    const first = wrapper.findAll('[data-testid=file-row]')[0]
    expect(first.get('[data-field=size]').attributes('data-raw')).toBe('1536')
    expect(first.get('[data-field=size]').text()).toBe('1.5 KiB')
    expect(flatten(data).map((cell) => cell.raw)).toEqual(['2', 'a/b.txt', 'file', '1536', 'a', 'dir'])
  })
})
